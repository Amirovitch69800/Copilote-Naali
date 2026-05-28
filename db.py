"""
db.py — SQLite persistence pour naali_planner
Tables : signals_relance (isolée par owner_id), auth (mots de passe hashés)
"""
import sqlite3
import os
import hashlib
import hmac
import secrets

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "naali.db")


def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


ACTIVE_OWNERS = [
    {"id": "727665403",  "firstName": "Amir",         "lastName": "Ounissi"},
    {"id": "78146570",   "firstName": "Icham",         "lastName": "Benaissa"},
    {"id": "32059428",   "firstName": "Fatima",        "lastName": "Brahim"},
    {"id": "30058900",   "firstName": "Emelyne",       "lastName": "Lahaies"},
    {"id": "32320882",   "firstName": "Jérémy",        "lastName": "Le Feur"},
    {"id": "30078898",   "firstName": "Samira",        "lastName": "Tayach"},
    {"id": "30198014",   "firstName": "Karim",         "lastName": "Bougatef"},
    {"id": "31053202",   "firstName": "Walid",         "lastName": "Walid"},
    {"id": "31113492",   "firstName": "Mariam",        "lastName": "Belhadj"},
    {"id": "31113493",   "firstName": "Ilias",         "lastName": "Tayach"},
    {"id": "31180246",   "firstName": "Ghiles",        "lastName": "Mohammedi"},
    {"id": "31271129",   "firstName": "Yanis",         "lastName": "Bedjguelal"},
    {"id": "32410784",   "firstName": "Samir",         "lastName": "Amrane"},
    {"id": "32861583",   "firstName": "Rym",           "lastName": "Ben Othman"},
    {"id": "33033631",   "firstName": "Mohammad-Ali",  "lastName": "Bacha"},
    {"id": "75994681",   "firstName": "Nadir",         "lastName": "Tayach"},
    {"id": "75994803",   "firstName": "Karim",         "lastName": "Boucenna"},
    {"id": "76547042",   "firstName": "Jérémie",       "lastName": "Druart"},
    {"id": "78018380",   "firstName": "Natoura",       "lastName": "Nour Ebad"},
    {"id": "78146109",   "firstName": "Rachid",        "lastName": "Kehel"},
    {"id": "78192029",   "firstName": "Abderhaman",    "lastName": "Nour Ebad"},
    {"id": "83336554",   "firstName": "Victor",        "lastName": "Munch"},
    {"id": "86090326",   "firstName": "Sonia",         "lastName": "Louertani"},
    {"id": "29151394",   "firstName": "Lucie",         "lastName": "Romagne"},
    {"id": "824062131",  "firstName": "Salomé",        "lastName": "Dussert"},
    {"id": "838961979",  "firstName": "Bilel",         "lastName": "Fouadla"},
    {"id": "1290126718", "firstName": "Firdaws",       "lastName": "Abou El Hnichat"},
    {"id": "1399538406", "firstName": "Imad",          "lastName": "Ghani"},
]


def init_db():
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS owners_cache (
                owner_id   TEXT PRIMARY KEY,
                first_name TEXT NOT NULL,
                last_name  TEXT NOT NULL
            )
        """)
        # Seed initial
        con.executemany("""
            INSERT OR IGNORE INTO owners_cache (owner_id, first_name, last_name)
            VALUES (:id, :firstName, :lastName)
        """, ACTIVE_OWNERS)
        con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                owner_id   TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                email      TEXT NOT NULL,
                csv_path   TEXT DEFAULT '',
                home_lat   REAL,
                home_lon   REAL,
                home_city  TEXT DEFAULT ''
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS offres (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                nom_offre        TEXT    NOT NULL,
                type_offre       TEXT    NOT NULL DEFAULT 'sell-in',
                cible_offre      TEXT    NOT NULL DEFAULT 'client',
                produits         TEXT    DEFAULT '',
                mecanique        TEXT    DEFAULT '',
                message_court    TEXT    DEFAULT '',
                support          TEXT    DEFAULT '',
                date_debut       TEXT    DEFAULT '',
                date_fin         TEXT    DEFAULT '',
                sans_date_limite INTEGER DEFAULT 0,
                statut           TEXT    DEFAULT 'active',
                created_at       TEXT    DEFAULT (datetime('now')),
                updated_at       TEXT    DEFAULT (datetime('now'))
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS signals_relance (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id   TEXT    NOT NULL,
                company_id TEXT    NOT NULL,
                date_rel   TEXT    NOT NULL,
                type_visite TEXT   DEFAULT '',
                meeting_id TEXT    DEFAULT '',
                updated_at TEXT    DEFAULT (datetime('now')),
                UNIQUE(owner_id, company_id)
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS auth (
                owner_id      TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                salt          TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS next_actions (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id          TEXT    NOT NULL,
                company_id        TEXT    NOT NULL,
                action_type       TEXT    NOT NULL,
                due_date          TEXT    NOT NULL,
                priority          TEXT    DEFAULT 'normal',
                status            TEXT    DEFAULT 'a_faire',
                note              TEXT    DEFAULT '',
                impacts_planning  INTEGER DEFAULT 0,
                source_meeting_id TEXT    DEFAULT '',
                created_at        TEXT    DEFAULT (datetime('now')),
                updated_at        TEXT    DEFAULT (datetime('now'))
            )
        """)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def get_users() -> dict:
    """Retourne {owner_id: profile_dict} depuis SQLite."""
    with _conn() as con:
        rows = con.execute("SELECT * FROM users").fetchall()
    return {
        r["owner_id"]: {
            "owner_id":  r["owner_id"],
            "name":      r["name"],
            "email":     r["email"],
            "csv_path":  r["csv_path"] or "",
            "home_lat":  r["home_lat"],
            "home_lon":  r["home_lon"],
            "home_city": r["home_city"] or "",
        }
        for r in rows
    }


def upsert_user(owner_id: str, name: str, email: str,
                csv_path: str = "", home_lat=None, home_lon=None, home_city: str = ""):
    with _conn() as con:
        con.execute("""
            INSERT INTO users (owner_id, name, email, csv_path, home_lat, home_lon, home_city)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner_id) DO UPDATE SET
                name      = excluded.name,
                email     = excluded.email,
                csv_path  = CASE WHEN excluded.csv_path != '' THEN excluded.csv_path ELSE users.csv_path END,
                home_lat  = COALESCE(excluded.home_lat,  users.home_lat),
                home_lon  = COALESCE(excluded.home_lon,  users.home_lon),
                home_city = CASE WHEN excluded.home_city != '' THEN excluded.home_city ELSE users.home_city END
        """, (owner_id, name, email, csv_path, home_lat, home_lon, home_city))


# ---------------------------------------------------------------------------
# Signals relance
# ---------------------------------------------------------------------------

def get_signals(owner_id: str) -> dict:
    """Retourne {company_id: {date, type, meeting_id}} pour un owner."""
    with _conn() as con:
        rows = con.execute(
            "SELECT company_id, date_rel, type_visite, meeting_id FROM signals_relance WHERE owner_id = ?",
            (owner_id,)
        ).fetchall()
    return {
        r["company_id"]: {
            "date":       r["date_rel"],
            "type":       r["type_visite"],
            "meeting_id": r["meeting_id"],
        }
        for r in rows
    }


def upsert_signal(owner_id: str, company_id: str, date_rel: str, type_visite: str = "", meeting_id: str = ""):
    with _conn() as con:
        con.execute("""
            INSERT INTO signals_relance (owner_id, company_id, date_rel, type_visite, meeting_id, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(owner_id, company_id) DO UPDATE SET
                date_rel    = excluded.date_rel,
                type_visite = excluded.type_visite,
                meeting_id  = excluded.meeting_id,
                updated_at  = datetime('now')
        """, (owner_id, str(company_id), date_rel, type_visite, str(meeting_id)))


def delete_signal(owner_id: str, company_id: str):
    with _conn() as con:
        con.execute(
            "DELETE FROM signals_relance WHERE owner_id = ? AND company_id = ?",
            (owner_id, str(company_id))
        )


# ---------------------------------------------------------------------------
# Offres commerciales
# ---------------------------------------------------------------------------

_OFFRE_FIELDS = [
    "nom_offre", "type_offre", "cible_offre", "produits", "mecanique",
    "message_court", "support", "date_debut", "date_fin",
    "sans_date_limite", "statut",
]

def _row_to_offre(r) -> dict:
    return {
        "id":               r["id"],
        "nom_offre":        r["nom_offre"],
        "type_offre":       r["type_offre"],
        "cible_offre":      r["cible_offre"],
        "produits":         r["produits"] or "",
        "mecanique":        r["mecanique"] or "",
        "message_court":    r["message_court"] or "",
        "support":          r["support"] or "",
        "date_debut":       r["date_debut"] or "",
        "date_fin":         r["date_fin"] or "",
        "sans_date_limite": bool(r["sans_date_limite"]),
        "statut":           r["statut"],
        "created_at":       r["created_at"],
        "updated_at":       r["updated_at"],
    }


def get_offres(statut: str = None) -> list:
    """Retourne toutes les offres, filtrées optionnellement par statut."""
    with _conn() as con:
        if statut:
            rows = con.execute(
                "SELECT * FROM offres WHERE statut = ? ORDER BY updated_at DESC", (statut,)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM offres ORDER BY statut DESC, updated_at DESC"
            ).fetchall()
    return [_row_to_offre(r) for r in rows]


def create_offre(data: dict) -> dict:
    """Crée une offre et retourne l'objet créé."""
    with _conn() as con:
        cur = con.execute("""
            INSERT INTO offres (nom_offre, type_offre, cible_offre, produits, mecanique,
                message_court, support, date_debut, date_fin, sans_date_limite, statut)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get("nom_offre", ""),
            data.get("type_offre", "sell-in"),
            data.get("cible_offre", "client"),
            data.get("produits", ""),
            data.get("mecanique", ""),
            data.get("message_court", ""),
            data.get("support", ""),
            data.get("date_debut", ""),
            data.get("date_fin", ""),
            1 if data.get("sans_date_limite") else 0,
            data.get("statut", "active"),
        ))
        offre_id = cur.lastrowid
        row = con.execute("SELECT * FROM offres WHERE id = ?", (offre_id,)).fetchone()
    return _row_to_offre(row)


def update_offre(offre_id: int, data: dict):
    """Met à jour une offre. Retourne l'offre mise à jour ou None si inexistante."""
    with _conn() as con:
        exists = con.execute("SELECT id FROM offres WHERE id = ?", (offre_id,)).fetchone()
        if not exists:
            return None
        con.execute("""
            UPDATE offres SET
                nom_offre        = ?,
                type_offre       = ?,
                cible_offre      = ?,
                produits         = ?,
                mecanique        = ?,
                message_court    = ?,
                support          = ?,
                date_debut       = ?,
                date_fin         = ?,
                sans_date_limite = ?,
                statut           = ?,
                updated_at       = datetime('now')
            WHERE id = ?
        """, (
            data.get("nom_offre", ""),
            data.get("type_offre", "sell-in"),
            data.get("cible_offre", "client"),
            data.get("produits", ""),
            data.get("mecanique", ""),
            data.get("message_court", ""),
            data.get("support", ""),
            data.get("date_debut", ""),
            data.get("date_fin", ""),
            1 if data.get("sans_date_limite") else 0,
            data.get("statut", "active"),
            offre_id,
        ))
        row = con.execute("SELECT * FROM offres WHERE id = ?", (offre_id,)).fetchone()
    return _row_to_offre(row)


def toggle_offre_statut(offre_id: int):
    """Bascule active ↔ inactive. Retourne l'offre mise à jour."""
    with _conn() as con:
        row = con.execute("SELECT * FROM offres WHERE id = ?", (offre_id,)).fetchone()
        if not row:
            return None
        new_statut = "inactive" if row["statut"] == "active" else "active"
        con.execute(
            "UPDATE offres SET statut = ?, updated_at = datetime('now') WHERE id = ?",
            (new_statut, offre_id)
        )
        row = con.execute("SELECT * FROM offres WHERE id = ?", (offre_id,)).fetchone()
    return _row_to_offre(row)


def delete_offre(offre_id: int) -> bool:
    with _conn() as con:
        n = con.execute("DELETE FROM offres WHERE id = ?", (offre_id,)).rowcount
    return n > 0


# ---------------------------------------------------------------------------
# Next actions
# ---------------------------------------------------------------------------

# Types terrain (influencent le planificateur)
PLANNING_ACTION_TYPES = {
    "rappeler",
    "reprogrammer_visite",
    "formation",
    "controle_pack",
    "reassort",
    "relance_offre",
}


def _row_to_action(r) -> dict:
    return {
        "id":                r["id"],
        "owner_id":          r["owner_id"],
        "company_id":        r["company_id"],
        "action_type":       r["action_type"],
        "due_date":          r["due_date"],
        "priority":          r["priority"],
        "status":            r["status"],
        "note":              r["note"] or "",
        "impacts_planning":  bool(r["impacts_planning"]),
        "source_meeting_id": r["source_meeting_id"] or "",
        "created_at":        r["created_at"],
    }


def create_next_action(owner_id: str, company_id: str, action_type: str,
                       due_date: str, priority: str = "normal", note: str = "",
                       impacts_planning: bool = None,
                       source_meeting_id: str = "") -> dict:
    """Crée une prochaine action. impacts_planning déduit du type si non fourni."""
    if impacts_planning is None:
        impacts_planning = action_type in PLANNING_ACTION_TYPES
    with _conn() as con:
        cur = con.execute("""
            INSERT INTO next_actions
              (owner_id, company_id, action_type, due_date, priority, note, impacts_planning, source_meeting_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (owner_id, str(company_id), action_type, due_date, priority,
              note, 1 if impacts_planning else 0, str(source_meeting_id)))
        row = con.execute("SELECT * FROM next_actions WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_action(row)


def get_next_actions(owner_id: str, company_id: str = None,
                     status: str = None, impacts_planning: bool = None) -> list:
    """Retourne les actions filtrées. Si company_id=None → toutes pour l'owner."""
    clauses, params = ["owner_id = ?"], [owner_id]
    if company_id:
        clauses.append("company_id = ?"); params.append(str(company_id))
    if status:
        clauses.append("status = ?"); params.append(status)
    if impacts_planning is not None:
        clauses.append("impacts_planning = ?"); params.append(1 if impacts_planning else 0)
    with _conn() as con:
        rows = con.execute(
            f"SELECT * FROM next_actions WHERE {' AND '.join(clauses)} ORDER BY due_date ASC",
            params
        ).fetchall()
    return [_row_to_action(r) for r in rows]


def update_next_action_status(action_id: int, status: str) -> bool:
    with _conn() as con:
        n = con.execute(
            "UPDATE next_actions SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, action_id)
        ).rowcount
    return n > 0


# ---------------------------------------------------------------------------
# Auth (mots de passe)
# ---------------------------------------------------------------------------

def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        'sha256', password.encode('utf-8'), salt.encode('utf-8'), 260_000
    ).hex()


def set_password(owner_id: str, password: str) -> None:
    """Hash et stocke le mot de passe pour un owner."""
    salt = secrets.token_hex(32)
    hashed = _hash_password(password, salt)
    with _conn() as con:
        con.execute("""
            INSERT INTO auth (owner_id, password_hash, salt)
            VALUES (?, ?, ?)
            ON CONFLICT(owner_id) DO UPDATE SET
                password_hash = excluded.password_hash,
                salt          = excluded.salt
        """, (owner_id, hashed, salt))


def check_password(owner_id: str, password: str) -> bool:
    """Vérifie le mot de passe. Utilise hmac.compare_digest pour éviter les timing attacks."""
    with _conn() as con:
        row = con.execute(
            "SELECT password_hash, salt FROM auth WHERE owner_id = ?", (owner_id,)
        ).fetchone()
    if not row:
        # Hasher quand même pour éviter l'énumération d'utilisateurs via timing
        _hash_password(password, "naali_dummy_salt_constant_000")
        return False
    return hmac.compare_digest(
        _hash_password(password, row["salt"]),
        row["password_hash"]
    )


def has_password(owner_id: str) -> bool:
    """Retourne True si l'utilisateur a déjà défini un mot de passe."""
    with _conn() as con:
        row = con.execute(
            "SELECT 1 FROM auth WHERE owner_id = ?", (owner_id,)
        ).fetchone()
    return row is not None


# Initialisation automatique au premier import
init_db()
