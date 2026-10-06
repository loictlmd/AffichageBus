#!/usr/bin/env python3
"""Écran JUNIA — Pygame, Python >= 3.9, Raspberry Pi.

Lancement normal : python3 affichagebusV3.py
Vérification locale : python3 affichagebusV3.py --demo --windowed
Aperçus sans réseau : python3 affichagebusV3.py --preview-dir apercus
Conserver le dossier icons/ de la V2 à côté de ce fichier.
"""
import argparse
import logging
import math
import os
import signal
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame
import requests

# ======================= CONFIGURATION =======================
BASE_DIR = Path(__file__).resolve().parent
PARIS = ZoneInfo("Europe/Paris")
# Particularité du flux MEL vérifiée le 02/10/2026 : heure locale étiquetée Z.
# On préfère la date de cle_tri, qui fournit réellement +02:00 / +01:00.
# Ce réglage ne concerne que le repli du flux bus, jamais la météo ni l'agenda.
MEL_BUS_Z_IS_LOCAL = True
NOM_STATION = "SOLFERINO"
STATION_VLILLE = "PALAIS RAMEAU"
DIRECTIONS = {
    "L5": ("MARCQ FERME AUX OIES", "HAUBOURDIN LE PARC"),
    "18": ("LOMME ANATOLE FRANCE", "VILLENEUVE D'ASCQ HOTEL DE VILLE"),
}
API_URL = "https://data.lillemetropole.fr/geoserver/ogc/features/v1/collections/dsp_ilevia:prochains_passages/items?f=application%2Fjson&limit=-1"
VLILLE_URL = "https://data.lillemetropole.fr/geoserver/wfs?SERVICE=WFS&REQUEST=GetFeature&VERSION=2.0.0&TYPENAMES=dsp_ilevia%3Avlille_temps_reel&OUTPUTFORMAT=application%2Fjson"
METEO_URL = "https://api.open-meteo.com/v1/forecast?latitude=50.6333&longitude=3.0667&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,windspeed_10m_max,weather_code&timezone=Europe/Paris"
ACTUAL_URL = "https://api.open-meteo.com/v1/forecast?latitude=50.633&longitude=3.0586&models=meteofrance_seamless&current=temperature_2m,relative_humidity_2m&forecast_days=1"
EVENTS_URL = "https://affichagejunia.pythonanywhere.com/api/events"

PAGE_SECONDS = 10
SIDEBAR_SECONDS = 5
FPS = 15                         # Dessin à 1 Hz hors animation des jauges.
PERIODS = {"bus": 60, "vlille": 60, "events": 60, "actual": 300, "forecast": 900}
HTTP_TIMEOUT = (3.0, 8.0)       # Connexion, puis attente de lecture.
MAX_JSON_BYTES = 32 * 1024 * 1024
LOGICAL_SIZE = (1920, 1080)
PAGE_NAMES = ("Vie de campus", "Prochains bus", "Météo", "V’Lille")

# Palette reprise de la V2 ; validation avec la charte actuelle à faire.
PURPLE = "#3F2A55"
ORANGE = "#FC5D33"
INK = "#30203F"
PAPER = "#F5F2F7"
WHITE = "#FFFFFF"
MUTED = "#73657F"
LILAC = "#E8DFEE"
PEACH = "#FFF0EB"
DARK_TILE = "#513B67"
SOFT_TEXT = "#D9CDE4"

JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MOIS = ("", "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre")
LOG = logging.getLogger("junia")


def now_paris():
    return datetime.now(PARIS)


def normalize(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).upper().split())


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def fmt(value, unit=""):
    n = number(value)
    if n is None:
        return "—"
    return f"{n:g}".replace(".", ",") + unit


def date_fr(value, year=False):
    return f"{JOURS[value.weekday()].capitalize()} {value.day} {MOIS[value.month]}" + (f" {value.year}" if year else "")


def parse_departure(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    # Les heures sans décalage sont interprétées en heure locale de Lille.
    return dt.replace(tzinfo=PARIS) if dt.tzinfo is None else dt.astimezone(PARIS)


def parse_bus_departure(item):
    """Normalise le flux MEL sans appliquer deux fois son décalage horaire."""
    candidate = str(item.get("cle_tri", "")).rsplit("/", 1)[-1]
    try:
        dt = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            return dt.astimezone(PARIS)
    except (ValueError, TypeError):
        pass
    raw = datetime.fromisoformat(str(item["heure_estimee_depart"]).replace("Z", "+00:00"))
    if raw.tzinfo is None or (MEL_BUS_Z_IS_LOCAL and raw.utcoffset() == timedelta(0)):
        return raw.replace(tzinfo=PARIS)
    return raw.astimezone(PARIS)


def remaining_minutes(departure, now):
    # Soustraction des timestamps : dates, passage de minuit et changements d'heure.
    return max(0, math.ceil((departure.timestamp() - now.timestamp()) / 60))


def upcoming(items, now, count=2):
    threshold = now.replace(second=0, microsecond=0).timestamp()
    return tuple(dt for dt in items if dt.timestamp() >= threshold)[:count]


def features(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise ValueError("Réponse GeoJSON invalide")
    return (f.get("properties", {}) for f in payload["features"] if isinstance(f, dict))


def parse_bus(payload):
    result = {(line, direction): [] for line, directions in DIRECTIONS.items() for direction in directions}
    for item in features(payload):
        if not isinstance(item, dict) or normalize(item.get("nom_station")) != normalize(NOM_STATION):
            continue
        line = str(item.get("code_ligne", ""))
        if line not in DIRECTIONS:
            continue
        # Conserve aussi une direction inhabituelle pour le résumé par ligne.
        direction = next((s for s in DIRECTIONS[line] if normalize(s) == normalize(item.get("sens_ligne"))), str(item.get("sens_ligne", "")))
        try:
            dt = parse_bus_departure(item)
            result.setdefault((line, direction), []).append(dt)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    # timestamp comme clé : les deux 02:30 du retour à l'heure d'hiver sont distincts.
    return {key: tuple(value for _, value in sorted({dt.timestamp(): dt for dt in values}.items()))
            for key, values in result.items()}


def parse_vlille(payload):
    for item in features(payload):
        if isinstance(item, dict) and normalize(item.get("nom")) == normalize(STATION_VLILLE):
            bikes, spaces = number(item.get("nb_velos_dispo")), number(item.get("nb_places_dispo"))
            if bikes is None or spaces is None or bikes < 0 or spaces < 0:
                raise ValueError("Disponibilités V’Lille invalides")
            return {"bikes": int(bikes), "spaces": int(spaces)}
    raise ValueError("Station V’Lille absente de la réponse")


def parse_actual(payload):
    current = payload.get("current", {}) if isinstance(payload, dict) else {}
    result = {"temperature": number(current.get("temperature_2m")), "humidity": number(current.get("relative_humidity_2m"))}
    if all(v is None for v in result.values()):
        raise ValueError("Météo actuelle absente")
    return result


def parse_forecast(payload):
    daily = payload.get("daily", {}) if isinstance(payload, dict) else {}
    dates = daily.get("time", [])
    if not isinstance(dates, list) or not dates:
        raise ValueError("Prévisions absentes")
    result = []
    def at(key, index):
        values = daily.get(key, [])
        return number(values[index]) if isinstance(values, list) and index < len(values) else None
    for i, value in enumerate(dates):
        try:
            day = datetime.fromisoformat(value).date()
        except (TypeError, ValueError):
            continue
        result.append({"date": day, "max": at("temperature_2m_max", i), "min": at("temperature_2m_min", i),
                       "rain": at("precipitation_sum", i), "wind": at("windspeed_10m_max", i), "code": at("weather_code", i)})
    if not result or not any(row["max"] is not None for row in result):
        raise ValueError("Prévisions incomplètes")
    return tuple(sorted(result, key=lambda row: row["date"]))


def parse_events(payload):
    if not isinstance(payload, list):
        raise ValueError("L’API événements doit renvoyer une liste")
    result = []
    for event in payload:
        if not isinstance(event, dict):
            continue
        try:
            start = parse_departure(f"{event['date']}T{event['time']}")
            title = str(event["title"]).strip()
            association = str(event["association"]).strip()
            if not title:
                continue
            result.append({"start": start, "title": title[:500], "association": association[:150]})
        except (KeyError, TypeError, ValueError):
            continue
    if payload and not result:
        raise ValueError("Aucun événement exploitable")
    return tuple(sorted(result, key=lambda row: row["start"].timestamp()))


def visible_events(items, now):
    # Pas de date de fin dans l'API : conserve les événements de la journée.
    return tuple(ev for ev in (items or ()) if ev["start"].date() >= now.date())


def next_event(items, now):
    events = visible_events(items, now)
    return next((ev for ev in events if ev["start"].timestamp() >= now.timestamp()), None)


def event_when(start, now):
    days = (start.date() - now.date()).days
    day = "Aujourd’hui" if days == 0 else "Demain" if days == 1 else f"{JOURS[start.weekday()].capitalize()} {start:%d/%m}"
    return f"{day} à {start:%H:%M}"


def event_countdown(start, now):
    minutes = remaining_minutes(start, now)
    if start.timestamp() <= now.timestamp():
        return "Aujourd’hui" if start.date() == now.date() else "À venir"
    if minutes < 60:
        return "Dans quelques instants" if minutes <= 1 else f"Dans {minutes} min"
    if minutes < 1440:
        hours, mins = divmod(minutes, 60)
        return f"Dans {hours} h" + (f" {mins:02d}" if mins else "")
    days = (start.date() - now.date()).days
    return "Demain" if days == 1 else f"Dans {days} jours"


def line_departures(records, line, now, count=2):
    """Prochains départs d'une ligne, avec leur destination réelle."""
    threshold = now.replace(second=0, microsecond=0).timestamp()
    values = {(dt.timestamp(), direction): (dt, direction)
              for (route, direction), times in records.items() if route == line
              for dt in times if dt.timestamp() >= threshold}
    return tuple(values[key] for key in sorted(values))[:count]


@dataclass(frozen=True)
class Source:
    data: Any = None
    updated_at: Optional[datetime] = None
    error: Optional[str] = None


class DataStore:
    """Les workers remplacent des snapshots ; Pygame ne s'exécute que sur le thread principal."""
    def __init__(self):
        self._lock = threading.Lock()
        self._sources = {key: Source() for key in PERIODS}
        self._version = 0

    def publish(self, name, data, stamp=None):
        with self._lock:
            self._sources[name] = Source(data, stamp or now_paris(), None)
            self._version += 1

    def fail(self, name, error):
        with self._lock:
            old = self._sources[name]
            self._sources[name] = Source(old.data, old.updated_at, str(error))
            self._version += 1

    def snapshot(self):
        with self._lock:
            return self._version, self._sources.copy()


def get_json(session, url):
    # Plafond mémoire + échéance totale même si un serveur envoie au compte-gouttes.
    started = time.monotonic()
    with session.get(url, timeout=HTTP_TIMEOUT, stream=True) as response:
        response.raise_for_status()
        body = bytearray()
        for chunk in response.iter_content(65536):
            body.extend(chunk)
            if len(body) > MAX_JSON_BYTES:
                raise ValueError("Réponse API trop volumineuse")
            if time.monotonic() - started > 25:
                raise TimeoutError("Délai total API dépassé")
        import json
        return json.loads(body)


def get_geojson(session, url):
    """Supporte aussi une réponse paginée, sans perdre les passages suivants."""
    payload = get_json(session, url)
    list(features(payload))              # Validation avant modification.
    all_features = payload["features"][:]
    seen = {url}
    for _ in range(50):
        next_url = next((link.get("href") for link in payload.get("links", [])
                         if isinstance(link, dict) and link.get("rel") == "next"), None)
        if not next_url:
            return {"features": all_features}
        next_url = urljoin(url, next_url)
        if next_url in seen or urlparse(next_url).netloc != urlparse(url).netloc or urlparse(next_url).scheme != "https":
            raise ValueError("Pagination API invalide")
        seen.add(next_url)
        payload = get_json(session, next_url)
        list(features(payload))
        all_features.extend(payload["features"])
        if len(all_features) > 200000:
            raise ValueError("Pagination API trop volumineuse")
    raise ValueError("Trop de pages API")


class Fetcher:
    def __init__(self, store):
        self.store = store
        self.stop_event = threading.Event()
        self.threads = []

    def start(self):
        jobs = {"bus": (API_URL, parse_bus, True), "vlille": (VLILLE_URL, parse_vlille, True),
                "actual": (ACTUAL_URL, parse_actual, False), "forecast": (METEO_URL, parse_forecast, False),
                "events": (EVENTS_URL, parse_events, False)}
        for name, (url, parser, geo) in jobs.items():
            thread = threading.Thread(target=self._run, args=(name, url, parser, geo), name=f"api-{name}", daemon=True)
            thread.start()
            self.threads.append(thread)

    def _run(self, name, url, parser, geo):
        failures = 0
        # Une session par worker : pas de partage concurrent de requests.Session.
        with requests.Session() as session:
            session.headers["User-Agent"] = "JUNIA-Hall-Display/3.1"
            while not self.stop_event.is_set():
                try:
                    payload = get_geojson(session, url) if geo else get_json(session, url)
                    self.store.publish(name, parser(payload))
                    failures = 0
                    delay = PERIODS[name]
                except Exception as exc:
                    failures += 1
                    self.store.fail(name, exc)
                    # Journal limité au rythme des tentatives, reprise progressive.
                    LOG.warning("%s : %s", name, exc)
                    delay = min(PERIODS[name], 15 * 2 ** min(failures - 1, 6))
                if self.stop_event.wait(delay):
                    break

    def stop(self):
        self.stop_event.set()
        deadline = time.monotonic() + 1
        for thread in self.threads:
            thread.join(max(0, deadline - time.monotonic()))


def status(source, name, now):
    return ""


def weather_kind(code):
    if code is None:
        return "cloudy", "Prévision"
    code = int(code)
    if code == 0:
        return "sunny", "Ensoleillé"
    if code in (1, 2):
        return "cloudy", "Éclaircies"
    if code == 3:
        return "cloudy", "Nuageux"
    if code in (45, 48):
        return "cloudy", "Brouillard"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow", "Neige"
    if code >= 95:
        return "storm", "Orages"
    return "rainy", "Pluie"


# ======================= RENDU =======================
class Canvas:
    """Coordonnées de référence 1920×1080, dessin direct à la résolution réelle."""
    def __init__(self, surface):
        self.surface = surface
        w, h = surface.get_size()
        self.scale = min(w / 1920, h / 1080)
        self.ox = (w - 1920 * self.scale) / 2
        self.oy = (h - 1080 * self.scale) / 2
        self.font_paths = {}
        for bold in (False, True):
            local = BASE_DIR / "fonts" / ("bold.ttf" if bold else "regular.ttf")
            self.font_paths[bold] = str(local) if local.exists() else pygame.font.match_font("dejavusans,liberationsans,arial", bold=bold)

    def point(self, x, y):
        return round(self.ox + x * self.scale), round(self.oy + y * self.scale)

    def rect(self, box, color, radius=0, width=0):
        x, y, w, h = box
        rect = pygame.Rect(*self.point(x, y), round(w * self.scale), round(h * self.scale))
        pygame.draw.rect(self.surface, color, rect, max(1, round(width * self.scale)) if width else 0,
                         border_radius=round(radius * self.scale))

    def line(self, start, end, color, width=2):
        pygame.draw.line(self.surface, color, self.point(*start), self.point(*end), max(1, round(width * self.scale)))

    def circle(self, x, y, radius, color, width=0):
        pygame.draw.circle(self.surface, color, self.point(x, y), max(1, round(radius * self.scale)),
                           max(1, round(width * self.scale)) if width else 0)

    def polygon(self, points, color):
        pygame.draw.polygon(self.surface, color, [self.point(*p) for p in points])

    @lru_cache(maxsize=48)
    def font(self, size, bold=False):
        return pygame.font.Font(self.font_paths[bold], max(8, round(size * self.scale)))

    @lru_cache(maxsize=512)
    def raster(self, text, size, color, bold):
        return self.font(size, bold).render(text, True, color)

    def width(self, text, size, bold=False):
        return self.font(size, bold).size(str(text))[0] / self.scale

    def shorten(self, text, size, max_width, bold=False):
        text = str(text)
        if self.width(text, size, bold) <= max_width:
            return text
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.width(text[:mid] + "…", size, bold) <= max_width:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo].rstrip() + "…"

    def text(self, text, x, y, size=30, color=INK, bold=False, max_width=None, align="left"):
        text = str(text)
        if max_width is not None:
            text = self.shorten(text, size, max_width, bold)
        image = self.raster(text, size, color, bold)
        px, py = self.point(x, y)
        if align == "right":
            px -= image.get_width()
        elif align == "center":
            px -= image.get_width() // 2
        self.surface.blit(image, (px, py))

    def wrapped(self, text, x, y, width, size=32, color=INK, bold=False, lines=2, leading=1.2):
        words = str(text).replace("\n", " ").split()
        output, current = [], ""
        while words:
            word = words.pop(0)
            proposed = (current + " " + word).strip()
            if current and self.width(proposed, size, bold) > width:
                output.append(current)
                current = word
            else:
                current = proposed
            if len(output) == lines - 1:
                current = " ".join([current] + words)
                words = []
        if current:
            output.append(current)
        for index, line in enumerate(output[:lines]):
            self.text(line, x, y + index * size * leading, size, color, bold, width)

    @lru_cache(maxsize=32)
    def original(self, name):
        path = BASE_DIR / "icons" / name
        if not path.is_file():
            return None
        try:
            return pygame.image.load(str(path)).convert_alpha()
        except (pygame.error, OSError):
            LOG.warning("Image illisible : %s", path)
            return None

    @lru_cache(maxsize=64)
    def scaled_image(self, name, width, height, nearest=False):
        image = self.original(name)
        if image is None:
            return None
        factor = min(width * self.scale / image.get_width(), height * self.scale / image.get_height())
        target = max(1, round(image.get_width() * factor)), max(1, round(image.get_height() * factor))
        transform = pygame.transform.scale if nearest else pygame.transform.smoothscale
        return transform(image, target)

    def image(self, name, box, nearest=False):
        x, y, w, h = box
        image = self.scaled_image(name, w, h, nearest)
        if image is None:
            return False
        px, py = self.point(x + w / 2, y + h / 2)
        self.surface.blit(image, image.get_rect(center=(px, py)))
        return True

    def pill(self, text, x, y, width, color=PURPLE, foreground=WHITE, size=23):
        self.rect((x, y, width, 38), color, 19)
        self.text(text, x + width / 2, y + (38 - self.font(size, True).get_height() / self.scale) / 2, size, foreground, True, width - 24, "center")

    def weather_icon(self, kind, x, y, size=100):
        # Images de la V2 prioritaires, chargées/redimensionnées une seule fois.
        if self.image(kind + ".png", (x, y, size, size)):
            return
        # Les images historiques n'incluent pas toujours neige et orage.
        fallback = {"snow": "cloudy.png", "storm": "rainy.png"}.get(kind)
        if fallback and self.image(fallback, (x, y, size, size)):
            return
        # Dessin de secours uniquement lorsqu'aucune image n'est disponible.
        unit = size / 100
        def p(a, b):
            return x + a * unit, y + b * unit
        if kind == "sunny":
            self.circle(*p(50, 48), 22 * unit, ORANGE)
            for a in range(0, 360, 45):
                angle = math.radians(a)
                self.line(p(50 + 31 * math.cos(angle), 48 + 31 * math.sin(angle)),
                          p(50 + 42 * math.cos(angle), 48 + 42 * math.sin(angle)), ORANGE, 4 * unit)
        else:
            for a, b, r in ((33, 49, 20), (53, 35, 25), (75, 51, 18)):
                self.circle(*p(a, b), r * unit, PURPLE)
            self.rect((*p(32, 48), 44 * unit, 22 * unit), PURPLE, 8 * unit)
            if kind in ("rainy", "storm", "snow"):
                for a in (30, 50, 70):
                    if kind == "snow":
                        self.circle(*p(a, 84), 4 * unit, ORANGE)
                    else:
                        self.line(p(a, 78), p(a - 5, 91), ORANGE, 4 * unit)

    def bus_icon(self, line, direction, x, y):
        suffix = "aller" if direction == DIRECTIONS[line][1] else "retour"
        if self.image(f"bus{line}{suffix}.png", (x - 38, y - 20, 76, 35)) or self.image(f"busL5{suffix}.png", (x - 38, y - 20, 76, 35)):
            return
        self.rect((x - 29, y - 19, 58, 30), ORANGE, 7)
        self.rect((x - 21, y - 13, 42, 11), WHITE, 2)
        for dx in (-17, 17):
            self.circle(x + dx, y + 12, 5, PURPLE)


class Renderer:
    def __init__(self, surface):
        self.c = Canvas(surface)

    def header(self, now):
        c = self.c
        c.rect((0, 0, 1920, 144), PURPLE)
        c.rect((0, 140, 1920, 4), ORANGE)
        if not c.image("junia.png", (65, 42, 176, 60)):
            c.text("JUNIA", 153, 40, 46, WHITE, True, align="center")
        c.line((267, 38), (267, 105), DARK_TILE, 2)
        c.text("LA VIE DU CAMPUS", 294, 38, 29, WHITE, True)
        c.text("Lille  /  Informations pratiques", 295, 81, 23, SOFT_TEXT)
        c.text(date_fr(now, year=True), 1528, 54, 28, WHITE, max_width=620, align="right")
        c.text(now.strftime("%H:%M"), 1868, 22, 74, WHITE, True, align="right")

    def heading(self, kicker, title, subtitle):
        c = self.c
        c.text(kicker.upper(), 48, 179, 23, ORANGE, True)
        c.text(title, 48, 216, 59, PURPLE, True, 1120)
        c.text(subtitle, 50, 291, 25, MUTED, max_width=1150)

    def source_note(self, sources, name, now, x=50, y=966):
        self.c.text(status(sources[name], name, now), x, y, 20, MUTED)

    def sidebar(self, sources, now, slot):
        c = self.c
        x, w = 1304, 568
        c.rect((x, 176, w, 856), PURPLE, 28)
        c.text("L’ESSENTIEL", x + 32, 203, 22, SOFT_TEXT, True)
        c.line((x + 32, 249), (x + w - 32, 249), DARK_TILE)
        actual = sources["actual"].data or {}
        c.text("Météo actuelle", x + 32, 274, 25, WHITE, True)
        has_temp = c.image("temp.png", (x + 30, 325, 48, 62))
        c.text(fmt(actual.get("temperature"), "°"), x + (92 if has_temp else 32), 314, 62, WHITE, True, 210)
        c.text("Lille", x + 34, 401, 22, SOFT_TEXT)
        c.line((x + 291, 328), (x + 291, 419), DARK_TILE, 2)
        has_humidity = c.image("humidity.png", (x + 325, 338, 38, 42))
        c.text(fmt(actual.get("humidity"), " %"), x + (374 if has_humidity else 331), 334, 37, WHITE, True, 170)
        c.text("Humidité", x + 331, 389, 22, SOFT_TEXT)
        c.text(status(sources["actual"], "actual", now), x + 32, 440, 18, SOFT_TEXT, max_width=w-64)
        c.line((x + 32, 477), (x + w - 32, 477), DARK_TILE)
        c.text("V’Lille", x + 32, 493, 28, WHITE, True)
        c.text("Palais Rameau", x + w - 32, 500, 23, SOFT_TEXT, align="right")
        vl = sources["vlille"].data
        bikes, spaces = (vl["bikes"], vl["spaces"]) if vl else (None, None)
        c.text(fmt(bikes), x + 32, 532, 48, WHITE, True)
        c.text("vélos", x + 129, 552, 23, SOFT_TEXT)
        c.text(fmt(spaces), x + 317, 532, 48, WHITE, True)
        c.text("places", x + 410, 552, 23, SOFT_TEXT)
        c.rect((x + 32, 600, w - 64, 9), DARK_TILE, 4)
        if vl and bikes + spaces:
            c.rect((x + 32, 600, (w - 64) * bikes / (bikes + spaces), 9), ORANGE, 4)
        c.text(status(sources["vlille"], "vlille", now), x + 32, 620, 17, SOFT_TEXT, max_width=w-64)

        c.rect((x + 20, 642, w - 40, 370), WHITE, 20)
        ev = next_event(sources["events"].data, now)
        if ev and slot % 2:
            c.text("PROCHAIN RENDEZ-VOUS", x + 44, 662, 20, MUTED, True)
            self.calendar(ev["start"], (x + 44, 717, 92, 122), PURPLE, WHITE)
            c.text(event_when(ev["start"], now), x + 156, 718, 23, ORANGE, True, w - 195)
            c.wrapped(ev["title"], x + 156, 765, w - 195, 30, PURPLE, True, 2, 1.1)
            c.text(event_countdown(ev["start"], now), x + 44, 887, 26, PURPLE, True, w - 88)
            c.pill(ev["association"], x + 44, 939, min(470, c.width(ev["association"], 20, True) + 30), LILAC, PURPLE, 20)
            c.text(status(sources["events"], "events", now), x + 44, 942, 17, MUTED, max_width=w-88)
        else:
            c.text("PROCHAINS BUS", x + 44, 662, 21, PURPLE, True)
            c.text("Solférino", x + w - 44, 663, 21, MUTED, align="right")
            buses = sources["bus"].data or {}
            for i, line in enumerate(DIRECTIONS):
                y = 711 + 143 * i
                c.rect((x + 36, y, w - 72, 131), PAPER, 14)
                c.pill(line, x + 48, y + 25, 59, PURPLE if i == 0 else ORANGE)
                next_times = line_departures(buses, line, now)
                if next_times:
                    dt, direction = next_times[0]
                    mins = remaining_minutes(dt, now)
                    c.text(dt.strftime("%H:%M"), x + 124, y + 23, 30, PURPLE, True)
                    c.text("Imminent" if mins == 0 else f"{mins} min", x + w - 50, y + 24, 28, PURPLE, True, 188, "right")
                    c.text("→ " + direction, x + 50, y + 79, 18, PURPLE, max_width=w - 100)
                    
                else:
                    c.text("Aucun passage annoncé", x + 124, y + 26, 21, MUTED, max_width=w-175)
                    c.text("En attente des prochains départs", x + 50, y + 79, 17, MUTED)
            c.text(status(sources["bus"], "bus", now), x + 44, 942, 17, MUTED, max_width=w-88)

    def calendar(self, dt, box, background=PEACH, foreground=PURPLE):
        c = self.c
        x, y, w, h = box
        c.rect(box, background, 16)
        c.text(JOURS[dt.weekday()][:3].upper() + ".", x + w / 2, y + 9, 17, foreground, True, align="center")
        c.text(str(dt.day).zfill(2), x + w / 2, y + h * 0.22, min(62, h * 0.43), foreground, True, align="center")
        c.text(MOIS[dt.month][:3].upper() + ".", x + w / 2, y + h - 30, 18, foreground, True, align="center")

    def event_qr_panel(self):
        c = self.c
        c.rect((978, 350, 286, 682), WHITE, 24)
        c.text("À VOUS DE JOUER", 1121, 426, 21, PURPLE, True, align="center")
        c.wrapped("Un événement à partager ?", 1004, 480, 234, 30, PURPLE, True, 2)
        if c.original("qrcode.png"):
            c.image("qrcode.png", (996, 597, 250, 250), nearest=True)
            c.wrapped("Scannez pour proposer votre événement.", 1004, 882, 234, 23, MUTED, lines=3)
        else:
            c.rect((1004, 603, 234, 244), PEACH, 20)
            c.text("LA VIE", 1121, 636, 39, ORANGE, True, align="center")
            c.text("DU", 1121, 695, 29, PURPLE, True, align="center")
            c.text("CAMPUS", 1121, 739, 39, PURPLE, True, align="center")
            c.wrapped("Associations, rencontres et temps forts.", 1004, 882, 234, 23, MUTED, lines=3)

    def event_tile(self, event, now, box, large=False):
        c = self.c
        x, y, w, h = box
        dt = event["start"]
        c.rect(box, WHITE, 22)
        c.rect((x, y + 24, 5, h - 48), ORANGE, 2)
        calendar_w = 116 if large else 82
        self.calendar(dt, (x + 24, y + 22, calendar_w, min(h - 44, 138 if large else 104)))
        tx = x + calendar_w + 46
        tw = w - calendar_w - 72
        c.text(event_when(dt, now), tx, y + 21, 23 if large else 20, ORANGE, True, tw)
        size = 36 if h >= 240 else 28
        c.wrapped(event["title"], tx, y + (68 if h >= 240 else 52), tw, size, PURPLE, True, 2, 1.08)
        c.pill(event["association"], tx, y + h - 47, min(tw, c.width(event["association"], 19, True) + 28), LILAC, PURPLE, 19)

    def events(self, sources, now, event_sheet):
        c = self.c
        events = visible_events(sources["events"].data, now)
        count = max(1, math.ceil(len(events) / 6))
        sheet = event_sheet % count
        batch = events[sheet * 6:sheet * 6 + 6]
        sparse = len(batch) <= 3
        c.text("RENDEZ-VOUS", 48, 179, 23, ORANGE, True)
        c.text("Ça se passe à JUNIA.", 48, 224, 58, PURPLE, True, 950)
        c.text("Les prochains temps forts de la vie étudiante", 50, 306, 25, MUTED, max_width=935)
        if sparse:
            self.event_qr_panel()
        elif c.original("qrcode.png"):
            c.rect((1045, 164, 220, 220), WHITE, 18)
            c.image("qrcode.png", (1055, 174, 200, 200), nearest=True)
        if not batch:
            c.rect((48, 350, 902, 682), WHITE, 24)
            c.wrapped("Le campus prépare la suite.", 88, 514, 790, 53, PURPLE, True, 2)
            message = "Aucun événement prévu." if sources["events"].data is not None else "Les événements seront affichés dès réception des données."
            c.wrapped(message, 88, 676, 790, 29, MUTED, lines=2)
        elif len(batch) == 1:
            ev, x, y, w = batch[0], 48, 350, 902
            c.rect((x, y, w, 682), PURPLE, 26)
            self.calendar(ev["start"], (x + 36, y + 36, 132, 152), WHITE, PURPLE)
            c.text("À L’AFFICHE", x + 202, y + 40, 23, ORANGE, True)
            c.text(event_when(ev["start"], now), x + 202, y + 85, 35, WHITE, True, w-238)
            c.text(event_countdown(ev["start"], now), x + 202, y + 141, 25, SOFT_TEXT)
            c.wrapped(ev["title"], x + 36, y + 281, w - 72, 61, WHITE, True, 3, 1.1)
            c.line((x + 36, y + 573), (x + w - 36, y + 573), DARK_TILE, 2)
            c.pill(ev["association"], x + 36, y + 611, min(565, c.width(ev["association"], 24, True) + 36), ORANGE, WHITE, 24)
            c.text(ev["start"].strftime("%H:%M"), x + w - 36, y + 594, 53, WHITE, True, align="right")
        elif sparse:
            height = (682 - (len(batch) - 1) * 16) / len(batch)
            for i, ev in enumerate(batch):
                self.event_tile(ev, now, (48, 350 + i * (height + 16), 902, height), large=True)
        else:
            rows = math.ceil(len(batch) / 2)
            height = (630 - (rows - 1) * 16) / rows
            for i, ev in enumerate(batch):
                self.event_tile(ev, now, (48 + (i % 2) * 620, 402 + (i // 2) * (height + 16), 596, height))
        self.source_note(sources, "events", now)
        if count > 1:
            c.text(f"Agenda {sheet + 1}/{count}", 1262, 1042, 20, MUTED, align="right")

    def buses(self, sources, now):
        c = self.c
        self.heading("Mobilité", "Votre prochain départ.", "Arrêt Solférino  /  Deux prochains passages par direction")
        records = sources["bus"].data or {}
        for index, (line, directions) in enumerate(DIRECTIONS.items()):
            y = 350 + index * 351
            c.rect((48, y, 1216, 331), WHITE, 22)
            c.pill(line, 72, y + 20, 74, PURPLE if index == 0 else ORANGE)
            for i, direction in enumerate(directions):
                x = 178 + i * 520
                c.text(direction, x, y + 22, 22, PURPLE, True, 490)
                departures = upcoming(records.get((line, direction), ()), now)
                if not departures:
                    c.text("Aucun passage annoncé", x, y + 74, 24, MUTED)
                for j, dt in enumerate(departures):
                    xx = x + j * 250
                    c.text(dt.strftime("%H:%M"), xx, y + 65, 36, PURPLE, True)
                    minutes = remaining_minutes(dt, now)
                    c.text("imminent" if minutes == 0 else f"dans {minutes} min", xx, y + 111, 21, MUTED)
            # Frise symétrique : chaque côté représente un sens, pas une position GPS.
            left, right, center, fy = 156, 1156, 656, y + 258
            c.line((left, fy), (right, fy), LILAC, 6)
            for minute in (-20, -10, -5, 0, 5, 10, 20):
                px = center + minute / 20 * (right - center)
                c.line((px, fy - 6), (px, fy + 6), ORANGE if minute == 0 else LILAC, 4)
                c.text("JUNIA" if minute == 0 else f"{abs(minute)} min", px, fy + 17, 18, PURPLE if minute == 0 else MUTED, minute == 0, align="center")
            markers = []
            for direction in directions:
                values = upcoming(records.get((line, direction), ()), now, 1)
                if values:
                    minutes = remaining_minutes(values[0], now)
                    if minutes <= 20:
                        sign = -1 if direction == directions[1] else 1
                        px = center + sign * minutes / 20 * (right - center)
                        markers.append((direction, px))
            close = len(markers) == 2 and abs(markers[0][1] - markers[1][1]) < 80
            for i, (direction, px) in enumerate(markers):
                c.bus_icon(line, direction, px, fy - 18 - (38 if close and i == 1 else 0))
            c.text("← " + directions[1].split(" ")[0], left, fy - 39, 17, MUTED)
            c.text(directions[0].split(" ")[0] + " →", right, fy - 39, 17, MUTED, align="right")
        self.source_note(sources, "bus", now)

    def weather(self, sources, now):
        c = self.c
        self.heading("Au fil de la journée", "Le temps à Lille.", "Météo actuelle et prévisions des trois prochains jours")
        c.rect((48, 350, 1216, 208), WHITE, 24)
        actual = sources["actual"].data or {}
        c.text("MAINTENANT", 80, 372, 21, ORANGE, True)
        has_temp = c.image("temp.png", (80, 419, 62, 75))
        c.text(fmt(actual.get("temperature"), "°C"), 162 if has_temp else 80, 410, 73, PURPLE, True, 282 if has_temp else 355)
        c.text("Température", 450, 442, 27, MUTED)
        c.line((704, 394), (704, 516), LILAC)
        has_humidity = c.image("humidity.png", (738, 421, 56, 70))
        c.text(fmt(actual.get("humidity"), " %"), 814 if has_humidity else 750, 414, 59, PURPLE, True, 229)
        c.text("Humidité", 1067, 442, 24, MUTED)
        c.text(status(sources["actual"], "actual", now), 82, 521, 18, MUTED)
        forecasts = {row["date"]: row for row in (sources["forecast"].data or ())}
        for i in range(3):
            day = now.date() + timedelta(days=i + 1)
            row = forecasts.get(day, {})
            x = 48 + 412 * i
            c.rect((x, 582, 392, 450), WHITE, 24)
            c.text("DEMAIN" if i == 0 else JOURS[day.weekday()].upper(), x + 26, 605, 24, PURPLE, True)
            c.text(f"{day.day} {MOIS[day.month]}", x + 366, 609, 19, MUTED, align="right")
            if row:
                kind, label = weather_kind(row["code"])
                c.weather_icon(kind, x + 20, 675, 116)
                c.text(fmt(row["max"], "°"), x + 160, 687, 53, PURPLE, True)
                c.text("/ " + fmt(row["min"], "°"), x + 160, 751, 28, MUTED)
                c.text(label, x + 28, 827, 24, PURPLE, True)
                c.text("Pluie", x + 28, 891, 22, MUTED)
                c.text(fmt(row["rain"], " mm"), x + 362, 891, 24, PURPLE, align="right")
                c.text("Vent", x + 28, 967, 22, MUTED)
                c.text(fmt(row["wind"], " km/h"), x + 362, 967, 24, PURPLE, align="right")
            else:
                c.wrapped("Prévisions indisponibles", x + 28, 735, 336, 30, MUTED)
        self.source_note(sources, "forecast", now)

    def ring(self, x, y, fraction, color):
        c = self.c
        c.circle(x, y, 129, LILAC, 18)
        fraction = min(1, max(0, fraction))
        if fraction <= 0:
            return
        count = max(2, math.ceil(180 * fraction))
        angles = [-math.pi / 2 + 2 * math.pi * fraction * i / count for i in range(count + 1)]
        outer = [(x + 129 * math.cos(a), y + 129 * math.sin(a)) for a in angles]
        inner = [(x + 111 * math.cos(a), y + 111 * math.sin(a)) for a in reversed(angles)]
        c.polygon(outer + inner, color)
        for a in (angles[0], angles[-1]):
            c.circle(x + 120 * math.cos(a), y + 120 * math.sin(a), 9, color)

    def bikes(self, sources, now, ring_progress):
        c = self.c
        self.heading("Mobilité douce", "À vélo, tout simplement.", "Station V’Lille  /  Palais Rameau")
        vl = sources["vlille"].data
        for i, label in enumerate(("Vélos disponibles", "Places libres")):
            x = 48 + 620 * i
            c.rect((x, 350, 596, 434), WHITE, 24)
            c.text(label, x + 32, 377, 31, PURPLE, True)
            count = vl["bikes" if i == 0 else "spaces"] if vl else None
            total = vl["bikes"] + vl["spaces"] if vl else 0
            pct = count / total if total else 0
            self.ring(x + 298, 594, pct * ring_progress, ORANGE if i == 0 else PURPLE)
            c.text(fmt(count), x + 298, 535, 81, PURPLE, True, align="center")
            c.text("vélos" if i == 0 else "places", x + 298, 632, 25, MUTED, align="center")
        c.rect((48, 808, 1216, 224), LILAC, 24)
        c.text("Un vélo pour votre prochain trajet.", 80, 862, 33, PURPLE, True, 810)
        c.text("Disponibilités de la station Palais Rameau", 82, 919, 24, MUTED, max_width=830)
        if not c.image("vlille.png", (940, 841, 300, 157)):
            # Illustration vectorielle de secours aux couleurs JUNIA.
            for wheel in (1010, 1180):
                c.circle(wheel, 952, 34, PURPLE, 5)
            for a, b in (((1010, 886), (1050, 822)), ((1050, 822), (1100, 886)), ((1100, 886), (1010, 886)),
                         ((1050, 822), (1150, 822)), ((1150, 822), (1100, 886)), ((1150, 822), (1180, 886)),
                         ((1150, 822), (1140, 795)), ((1140, 795), (1170, 795))):
                c.line((a[0], a[1] + 66), (b[0], b[1] + 66), ORANGE, 6)
            c.line((1028, 884), (1067, 884), PURPLE, 5)
        self.source_note(sources, "vlille", now)

    def footer(self, page, demo):
        c = self.c
        if demo:
            c.text("DÉMONSTRATION · DONNÉES FICTIVES", 1872, 1041, 15, MUTED, align="right")

    def draw(self, page, sources, now, elapsed, event_sheet=0, ring_progress=1, demo=False):
        self.c.surface.fill(PAPER)
        self.header(now)
        if page == 0:
            self.events(sources, now, event_sheet)
        elif page == 1:
            self.buses(sources, now)
        elif page == 2:
            self.weather(sources, now)
        else:
            self.bikes(sources, now, ring_progress)
        self.sidebar(sources, now, int(elapsed // SIDEBAR_SECONDS))
        self.footer(page, demo)


def demo_store(now):
    """Données fictives uniquement, jamais utilisées dans le fonctionnement normal."""
    store = DataStore()
    store.publish("actual", {"temperature": 18, "humidity": 64}, now)
    store.publish("vlille", {"bikes": 12, "spaces": 8}, now)
    buses = {}
    for i, (line, directions) in enumerate(DIRECTIONS.items()):
        for j, direction in enumerate(directions):
            buses[(line, direction)] = tuple(now + timedelta(minutes=3 + i * 3 + j * 4 + k * 9) for k in range(2))
    store.publish("bus", buses, now)
    titles = [("Afterwork de rentrée", "BDE"), ("Rencontre avec les associations", "Vie de campus"),
              ("Atelier découverte de la robotique", "Club Robotique"), ("Un projet, une rencontre", "Junia Lille Études"),
              ("Tournoi interpromotions", "BDS"), ("Soirée des talents", "BDA")]
    events = []
    for i, (title, association) in enumerate(titles):
        start = (now + timedelta(days=i)).replace(hour=18, minute=30)
        events.append({"start": start, "title": title, "association": association})
    store.publish("events", tuple(events), now)
    store.publish("forecast", tuple({"date": now.date() + timedelta(days=i + 1), "max": [20, 17, 19][i], "min": [12, 11, 10][i],
                                     "rain": [0, 2.4, 0][i], "wind": [12, 18, 14][i], "code": [0, 61, 2][i]} for i in range(3)), now)
    return store


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windowed", action="store_true", help="Fenêtre de test au lieu du plein écran")
    parser.add_argument("--size", default="1920x1080", help="Taille de la fenêtre/des aperçus (ex. 1280x720)")
    parser.add_argument("--demo", action="store_true", help="Données fictives, aucun appel réseau")
    parser.add_argument("--preview-dir", type=Path, help="Enregistre les quatre pages fictives puis quitte")
    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.preview_dir:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.display.init()
    pygame.font.init()              # Pas d'initialisation du son sur le Raspberry Pi.
    fetcher = None
    try:
        try:
            width, height = map(int, args.size.lower().split("x"))
            if width < 640 or height < 360:
                raise ValueError
        except ValueError:
            raise SystemExit("--size doit être de la forme 1920x1080 (minimum 640x360)")
        screen = pygame.display.set_mode((width, height) if args.windowed or args.preview_dir else (0, 0),
                                         0 if args.windowed or args.preview_dir else pygame.FULLSCREEN)
        pygame.display.set_caption("JUNIA · La vie du campus")
        pygame.mouse.set_visible(args.windowed)
        renderer = Renderer(screen)
        demo = args.demo or bool(args.preview_dir)
        now = now_paris()
        store = demo_store(now) if demo else DataStore()
        if args.preview_dir:
            args.preview_dir.mkdir(parents=True, exist_ok=True)
            _, sources = store.snapshot()
            for page, name in enumerate(("01_evenements", "02_bus", "03_meteo", "04_vlille")):
                renderer.draw(page, sources, now, page * PAGE_SECONDS + 2, demo=True)
                pygame.image.save(screen, str(args.preview_dir / (name + ".png")))
            return
        if not demo:
            fetcher = Fetcher(store)
            fetcher.start()
        running = True
        def request_stop(_signum, _frame):
            nonlocal running
            running = False
        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)
        clock = pygame.time.Clock()
        origin = time.monotonic()
        last_signature = None
        last_page, last_bikes, animation_start = None, None, 0
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                    running = False
            if not running:
                break
            mono = time.monotonic()
            elapsed = mono - origin
            page = int(elapsed // PAGE_SECONDS) % 4
            now = now_paris()
            version, sources = store.snapshot()
            bikes = sources["vlille"].data
            if page == 3 and (page != last_page or bikes != last_bikes):
                animation_start = mono
            animating = page == 3 and mono - animation_start < 0.65
            fraction = min(1, (mono - animation_start) / 0.65) if page == 3 else 1
            ease = 1 - (1 - fraction) ** 3
            signature = (version, page, int(elapsed), now.strftime("%Y%m%d%H%M"), round(fraction, 2) if animating else 1)
            if signature != last_signature:
                renderer.draw(page, sources, now, elapsed, int(elapsed // (PAGE_SECONDS * 4)), ease, demo)
                pygame.display.flip()
                last_signature = signature
            last_page, last_bikes = page, bikes
            clock.tick(FPS)
    finally:
        if fetcher:
            fetcher.stop()
        pygame.quit()


if __name__ == "__main__":
    main()
