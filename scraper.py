#!/usr/bin/env python3
"""
Veille des annonces de logement CROUS (trouverunlogement.lescrous.fr).

Principe : la page cible est une application cliente (SPA) ; les données
de recherche sont soit injectées côté serveur dans un <script> JSON
(motif Nuxt/Next classique), soit chargées via un appel XHR déclenché par
le JavaScript après coup. Ce script tente d'abord l'extraction JSON
serveur ; à défaut, il retombe sur un parsing HTML générique et écrit
systématiquement un fichier de diagnostic (debug_last_page.html) pour
permettre l'ajustement des sélecteurs si la structure réelle diffère.

État persistant : liste des identifiants d'annonces déjà vues, stockée
dans seen_listings.json (fichier committé par le workflow GitHub Actions
entre deux exécutions).
"""

import json
import os
import re
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SEARCH_URL = (
    "https://trouverunlogement.lescrous.fr/tools/47/search"
    "?bounds=4.7718134_45.8082628_4.8983774_45.7073666&locationName=Lyon"
)

STATE_FILE = Path(__file__).parent / "seen_listings.json"
DEBUG_FILE = Path(__file__).parent / "debug_last_page.html"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# Motifs plausibles pour retrouver un état JSON injecté côté serveur
# (Nuxt : __NUXT_DATA__ / __NUXT__, Next : __NEXT_DATA__).
JSON_STATE_PATTERNS = [
    re.compile(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S),
    re.compile(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.S),
    re.compile(r"window\.__NUXT__\s*=\s*(\{.*?\});", re.S),
]


def fetch_page():
    resp = requests.get(SEARCH_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def extract_via_embedded_json(html):
    """Tente de repérer un bloc JSON serveur contenant les annonces."""
    for pattern in JSON_STATE_PATTERNS:
        match = pattern.search(html)
        if not match:
            continue
        raw = match.group(1)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        listings = _search_listings_in_json(data)
        if listings:
            return listings
    return None


def _search_listings_in_json(node, depth=0):
    """Parcourt récursivement un objet JSON à la recherche d'une liste
    d'objets ressemblant à des annonces (présence de clés id + adresse
    ou loyer)."""
    if depth > 12:
        return None
    if isinstance(node, list):
        if node and all(isinstance(i, dict) for i in node):
            keys = set()
            for item in node[:3]:
                keys |= item.keys()
            if {"id"} & keys and (
                {"address", "adresse", "rent", "loyer", "title", "libelle"} & keys
            ):
                return node
        for item in node:
            found = _search_listings_in_json(item, depth + 1)
            if found:
                return found
    elif isinstance(node, dict):
        for value in node.values():
            found = _search_listings_in_json(value, depth + 1)
            if found:
                return found
    return None


def extract_via_html_cards(html):
    """Repli générique : cherche des blocs répétés contenant un lien et
    un texte, potentiellement représentatifs des annonces. À affiner une
    fois la structure réelle observée (cf. debug_last_page.html)."""
    soup = BeautifulSoup(html, "html.parser")
    candidates = soup.select("[class*='card'], [class*='result'], [class*='item'], li, article")
    listings = []
    for el in candidates:
        link = el.find("a", href=True)
        if not link:
            continue
        text = " ".join(el.get_text(" ", strip=True).split())
        if len(text) < 5:
            continue
        listings.append({"id": link["href"], "title": text[:200], "url": link["href"]})
    # Déduplication par id
    dedup = {l["id"]: l for l in listings}
    return list(dedup.values())


def normalize(listings):
    normalized = []
    for item in listings:
        listing_id = str(
            item.get("id") or item.get("url") or item.get("href") or json.dumps(item, sort_keys=True)
        )
        title = item.get("title") or item.get("libelle") or item.get("address") or item.get("adresse") or ""
        url = item.get("url") or item.get("href") or ""
        if url and url.startswith("/"):
            url = "https://trouverunlogement.lescrous.fr" + url
        normalized.append({"id": listing_id, "title": title, "url": url})
    return normalized


def load_seen():
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def save_seen(ids):
    STATE_FILE.write_text(json.dumps(sorted(ids), ensure_ascii=False, indent=2))


def send_email(new_listings):
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    sender = os.environ["EMAIL_ADDRESS"]
    password = os.environ["EMAIL_PASSWORD"]
    recipient = os.environ.get("RECIPIENT_EMAIL", sender)

    lines = ["Nouvelle(s) annonce(s) détectée(s) sur Trouver un logement CROUS (Lyon) :", ""]
    for listing in new_listings:
        lines.append(f"- {listing['title']}")
        if listing["url"]:
            lines.append(f"  {listing['url']}")
    lines.append("")
    lines.append(SEARCH_URL)
    body = "\n".join(lines)

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"[CROUS Lyon] {len(new_listings)} nouvelle(s) annonce(s)"
    msg["From"] = sender
    msg["To"] = recipient

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, [recipient], msg.as_string())


def main():
    html = fetch_page()
    DEBUG_FILE.write_text(html, encoding="utf-8")

    raw_listings = extract_via_embedded_json(html)
    source = "json"
    if not raw_listings:
        raw_listings = extract_via_html_cards(html)
        source = "html"

    listings = normalize(raw_listings)
    print(f"[{source}] {len(listings)} annonce(s) trouvée(s) sur la page.", file=sys.stderr)

    seen = load_seen()
    current_ids = {l["id"] for l in listings}
    new_ids = current_ids - seen
    new_listings = [l for l in listings if l["id"] in new_ids]

    if new_listings and seen:  # ne pas alerter dès la toute première exécution
        print(f"{len(new_listings)} nouvelle(s) annonce(s) : envoi de l'email.", file=sys.stderr)
        send_email(new_listings)
    elif not seen:
        print("Première exécution : initialisation de l'état, aucun email envoyé.", file=sys.stderr)
    else:
        print("Aucune nouveauté.", file=sys.stderr)

    save_seen(current_ids)


if __name__ == "__main__":
    main()
