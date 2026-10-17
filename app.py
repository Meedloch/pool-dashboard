"""Suivi d'entretien de piscines — Flask + PostgreSQL local, sans JavaScript."""
import csv, io, math, os, secrets
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps

import click
import psycopg
from psycopg.rows import dict_row
from flask import (Flask, Response, abort, flash, g, redirect, render_template,
                   request, session, url_for)
from markupsafe import Markup, escape
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ["SECRET_KEY"],
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "1") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=14),
    MAX_CONTENT_LENGTH=64 * 1024,
)
DSN = os.environ.get("DATABASE_URL", "postgresql:///piscine")
DUMMY_HASH = generate_password_hash("dummy-password-for-timing")

# (colonne, libellé, type) — n=numérique, b=booléen, t=texte
COLS = [
    ("ph", "pH", "n"), ("free_chlorine", "Chlore libre", "n"),
    ("total_chlorine", "Chlore total", "n"), ("combined_chlorine", "Chlore combiné", "n"),
    ("tac", "TAC", "n"), ("th", "TH", "n"), ("temp", "Temp. °C", "n"),
    ("baskets", "Paniers", "b"), ("waterline", "Ligne d’eau", "b"),
    ("floor_walls", "Fond/parois", "b"), ("filter_washed", "Filtre lavé", "b"),
    ("pressure", "Pression", "n"), ("flow_checked", "Débit", "b"),
    ("water_state", "État eau", "t"), ("products", "Produits", "t"), ("notes", "Observations", "t"),
]
NUM_FIELDS = [  # champs numériques du formulaire : (colonne, libellé, min, max)
    ("ph", "pH", 0, 14), ("free_chlorine", "Chlore libre", 0, None),
    ("total_chlorine", "Chlore total", 0, None), ("combined_chlorine", "Chlore combiné", 0, None),
    ("tac", "TAC", 0, None), ("th", "TH", 0, None),
    ("temp", "Température (°C)", -10, 60), ("pressure", "Pression filtre", 0, None),
]
BOOL_FIELDS = [
    ("baskets", "Paniers nettoyés"), ("waterline", "Ligne d’eau nettoyée"),
    ("floor_walls", "Fond / parois nettoyés"), ("filter_washed", "Filtre lavé"),
    ("flow_checked", "Débit vérifié"),
]
WATER_STATES = ["Claire", "Trouble", "Verte", "Colorée", "Mousseuse", "Autre"]
CHART_DEFS = [("ph", "pH"), ("free_chlorine", "Chlore libre"), ("total_chlorine", "Chlore total"),
              ("combined_chlorine", "Chlore combiné"), ("tac", "TAC"), ("th", "TH"),
              ("temp", "Température (°C)"), ("pressure", "Pression filtre")]
COL_NAMES = [c[0] for c in COLS]


# ---------------------------------------------------------------- base de données
def db():
    if "db" not in g:
        g.db = psycopg.connect(DSN, row_factory=dict_row)
    return g.db


@app.teardown_appcontext
def close_db(exc):
    c = g.pop("db", None)
    if c is not None:
        c.close()


def query(sql, args=(), one=False):
    conn = db()
    cur = conn.execute(sql, args)
    rows = cur.fetchall() if cur.description else []
    conn.commit()
    return (rows[0] if rows else None) if one else rows


# ---------------------------------------------------------------- sécurité
def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


@app.context_processor
def inject():
    return {"csrf_input": lambda: Markup('<input type="hidden" name="csrf" value="%s">' % escape(csrf_token())),
            "csrf_token": csrf_token, "cell": cell, "fr_date": fr_date, "num": fmt_num}


@app.before_request
def load_user():
    g.user = None
    uid = session.get("uid")
    if uid:
        g.user = query("select * from users where id=%s and active", (uid,), one=True)
        if g.user is None:
            session.clear()
    if request.method in ("POST", "PUT", "DELETE"):
        tok = session.get("csrf", "")
        sent = request.form.get("csrf", "") or request.headers.get("X-CSRF-Token", "")
        if not tok or not secrets.compare_digest(tok, sent):
            abort(400)


@app.after_request
def headers(resp):
    resp.headers["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'self'; img-src 'self' data:; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "same-origin"
    if g.get("user"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if g.user is None:
            if request.path.startswith("/api/"):
                abort(401)
            return redirect(url_for("login"))
        return f(*a, **k)
    return w


def admin_required(f):
    @wraps(f)
    @login_required
    def w(*a, **k):
        if g.user["role"] != "admin":
            abort(403)
        return f(*a, **k)
    return w


def get_pool(pool_id):
    """Renvoie la piscine si l'utilisateur y a droit, sinon 404 (pas de fuite d'existence)."""
    if g.user["role"] == "admin":
        p = query("select * from pools where id=%s", (pool_id,), one=True)
    else:
        p = query("select p.* from pools p join pool_access a on a.pool_id=p.id "
                  "where p.id=%s and a.user_id=%s", (pool_id, g.user["id"]), one=True)
    if p is None:
        abort(404)
    return p


# ---------------------------------------------------------------- formatage
def fmt_num(v):
    if v is None or v == "":
        return ""
    s = format(Decimal(v).normalize(), "f")
    return s


def cell(v, kind):
    if kind == "b":
        return "Oui" if v else "Non"
    if kind == "n":
        return fmt_num(v) or "—"
    return v or "—"


def fr_date(d):
    return d.strftime("%d/%m/%Y") if d else "—"


def parse_check(form):
    errors, vals = [], {}
    try:
        vals["check_date"] = date.fromisoformat(form.get("check_date", ""))
    except ValueError:
        errors.append("La date est obligatoire.")
    for col, label, lo, hi in NUM_FIELDS:
        raw = form.get(col, "").strip().replace(",", ".")
        if not raw:
            vals[col] = None
            continue
        try:
            n = Decimal(raw)
            if not n.is_finite():
                raise InvalidOperation
        except InvalidOperation:
            errors.append(f"{label} : valeur numérique invalide.")
            continue
        if (lo is not None and n < lo) or (hi is not None and n > hi):
            errors.append(f"{label} : valeur hors limites.")
            continue
        vals[col] = n
    for col, _ in BOOL_FIELDS:
        vals[col] = form.get(col) == "on"
    ws = form.get("water_state", "").strip()
    if ws and ws not in WATER_STATES:
        errors.append("État de l’eau invalide.")
    vals["water_state"] = ws or None
    vals["products"] = form.get("products", "").strip()[:300] or None
    vals["notes"] = form.get("notes", "").strip()[:1000] or None
    return vals, errors


# ---------------------------------------------------------------- authentification
@app.route("/")
def index():
    return redirect(url_for("pools"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        u = query("select * from users where lower(email)=%s and active", (email,), one=True)
        ok = check_password_hash(u["password_hash"] if u else DUMMY_HASH, request.form.get("password", ""))
        if u and ok:
            session.clear()
            session.permanent = True
            session["uid"] = u["id"]
            csrf_token()
            return redirect(url_for("pools"))
        flash("Identifiants incorrects.", "err")
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------- consultation (admin + clients)
@app.route("/piscines")
@login_required
def pools():
    rows = query("""
        select p.*, c.check_date, c.ph, c.free_chlorine, c.water_state,
               (select count(*) from pool_checks where pool_id=p.id) as n
        from pools p
        left join lateral (select * from pool_checks where pool_id=p.id
                           order by check_date desc, id desc limit 1) c on true
        where %(adm)s or exists (select 1 from pool_access a where a.pool_id=p.id and a.user_id=%(uid)s)
        order by p.name""", {"adm": g.user["role"] == "admin", "uid": g.user["id"]})
    if g.user["role"] == "client" and len(rows) == 1:
        return redirect(url_for("pool_history", pool_id=rows[0]["id"]))
    return render_template("pools.html", pools=rows)


@app.route("/piscines/<int:pool_id>")
@login_required
def pool_history(pool_id):
    """Page unique (comme l'application d'origine) ; les données passent par /api."""
    return render_template("app.html", pool=get_pool(pool_id), num_fields=NUM_FIELDS,
                           bool_fields=BOOL_FIELDS, water_states=WATER_STATES, cols=COLS)


@app.route("/piscines/<int:pool_id>/export.csv")
@login_required
def pool_export(pool_id):
    get_pool(pool_id)
    rows = query("select * from pool_checks where pool_id=%s order by check_date desc, id desc", (pool_id,))
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_ALL)
    w.writerow(["Date"] + [c[1] for c in COLS])
    for r in rows:
        w.writerow([r["check_date"].isoformat()] + [cell(r[c], k) if k != "t" else (r[c] or "") for c, _, k in COLS])
        # neutralise l'injection de formules Excel dans les champs texte
    out = buf.getvalue().replace('"=', '"\'=').replace('"+', '"\'+').replace('"@', '"\'@')
    return Response("\ufeff" + out, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=piscine_{pool_id}.csv"})


# ---------------------------------------------------------------- API JSON
def check_json(r):
    d = {"id": r["id"], "check_date": r["check_date"].isoformat()}
    for c, _, k in COLS:
        d[c] = float(r[c]) if k == "n" and r[c] is not None else r[c]
    return d


def api_form(data):
    """Normalise le JSON reçu pour réutiliser parse_check()."""
    if not isinstance(data, dict):
        return {}
    return {k: "on" if v is True else ("" if v in (False, None) else str(v)) for k, v in data.items()}


def get_check(cid):
    c = query("select * from pool_checks where id=%s", (cid,), one=True)
    if c is None:
        abort(404)
    return c, get_pool(c["pool_id"])


@app.get("/api/pools/<int:pool_id>/checks")
@login_required
def api_checks(pool_id):
    get_pool(pool_id)
    rows = query("select * from pool_checks where pool_id=%s order by check_date desc, id desc", (pool_id,))
    return {"checks": [check_json(r) for r in rows]}


@app.post("/api/pools/<int:pool_id>/checks")
@admin_required
def api_check_create(pool_id):
    get_pool(pool_id)
    vals, errors = parse_check(api_form(request.get_json(silent=True)))
    if errors:
        return {"errors": errors}, 400
    cols = ["check_date"] + COL_NAMES
    row = query(f"insert into pool_checks (pool_id, created_by, {', '.join(cols)}) "
                f"values (%s, %s, {', '.join(['%s'] * len(cols))}) returning *",
                [pool_id, g.user["id"]] + [vals[c] for c in cols], one=True)
    return {"check": check_json(row)}, 201


@app.put("/api/checks/<int:cid>")
@admin_required
def api_check_update(cid):
    get_check(cid)
    vals, errors = parse_check(api_form(request.get_json(silent=True)))
    if errors:
        return {"errors": errors}, 400
    cols = ["check_date"] + COL_NAMES
    row = query(f"update pool_checks set {', '.join(c + '=%s' for c in cols)}, updated_at=now() "
                f"where id=%s returning *", [vals[c] for c in cols] + [cid], one=True)
    return {"check": check_json(row)}


@app.delete("/api/checks/<int:cid>")
@admin_required
def api_check_delete(cid):
    get_check(cid)
    query("delete from pool_checks where id=%s", (cid,))
    return {"ok": True}


# ---------------------------------------------------------------- administration
@app.route("/admin/piscines", methods=["GET", "POST"])
@admin_required
def admin_pools():
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:120]
        if not name:
            flash("Le nom de la piscine est obligatoire.", "err")
        else:
            p = query("insert into pools (name, address) values (%s,%s) returning id",
                      (name, request.form.get("address", "").strip()[:200] or None), one=True)
            flash("Piscine créée. Associez-lui maintenant ses clients.")
            return redirect(url_for("admin_pool", pool_id=p["id"]))
    rows = query("""select p.*, (select count(*) from pool_access where pool_id=p.id) as nclients,
                    (select count(*) from pool_checks where pool_id=p.id) as nchecks
                    from pools p order by p.name""")
    return render_template("admin_pools.html", pools=rows)


@app.route("/admin/piscines/<int:pool_id>", methods=["GET", "POST"])
@admin_required
def admin_pool(pool_id):
    pool = get_pool(pool_id)
    clients = query("select id, name, email, active from users where role='client' order by name")
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:120]
        if not name:
            flash("Le nom est obligatoire.", "err")
        else:
            wanted = {int(x) for x in request.form.getlist("clients") if x.isdigit()}
            wanted &= {c["id"] for c in clients}
            conn = db()
            conn.execute("update pools set name=%s, address=%s where id=%s",
                         (name, request.form.get("address", "").strip()[:200] or None, pool_id))
            conn.execute("delete from pool_access where pool_id=%s", (pool_id,))
            for uid in wanted:
                conn.execute("insert into pool_access (user_id, pool_id) values (%s,%s)", (uid, pool_id))
            conn.commit()
            flash("Piscine mise à jour.")
            return redirect(url_for("admin_pool", pool_id=pool_id))
    granted = {r["user_id"] for r in query("select user_id from pool_access where pool_id=%s", (pool_id,))}
    return render_template("admin_pool.html", pool=pool, tab="admin", clients=clients, granted=granted)


@app.route("/admin/piscines/<int:pool_id>/supprimer", methods=["GET", "POST"])
@admin_required
def admin_pool_delete(pool_id):
    pool = get_pool(pool_id)
    if request.method == "POST":
        query("delete from pools where id=%s", (pool_id,))
        flash("Piscine et historique supprimés.")
        return redirect(url_for("admin_pools"))
    n = query("select count(*) as n from pool_checks where pool_id=%s", (pool_id,), one=True)["n"]
    return render_template("confirm_pool_delete.html", pool=pool, n=n)


@app.route("/admin/utilisateurs", methods=["GET", "POST"])
@admin_required
def admin_users():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        name = request.form.get("name", "").strip()[:120]
        pw = request.form.get("password", "")
        role = "admin" if request.form.get("role") == "admin" else "client"
        if "@" not in email or not name or len(pw) < 10:
            flash("E-mail, nom et mot de passe (10 caractères minimum) sont obligatoires.", "err")
        else:
            try:
                query("insert into users (email, name, password_hash, role) values (%s,%s,%s,%s)",
                      (email, name, generate_password_hash(pw), role))
                flash("Utilisateur créé.")
                return redirect(url_for("admin_users"))
            except psycopg.errors.UniqueViolation:
                db().rollback()
                flash("Cet e-mail existe déjà.", "err")
    rows = query("""select u.*, (select count(*) from pool_access where user_id=u.id) as npools
                    from users u order by role, name""")
    return render_template("admin_users.html", users=rows)


@app.route("/admin/utilisateurs/<int:uid>", methods=["GET", "POST"])
@admin_required
def admin_user(uid):
    u = query("select * from users where id=%s", (uid,), one=True)
    if u is None:
        abort(404)
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:120]
        active = request.form.get("active") == "on" or u["id"] == g.user["id"]
        pw = request.form.get("password", "")
        if not name or (pw and len(pw) < 10):
            flash("Nom obligatoire ; mot de passe de 10 caractères minimum.", "err")
        else:
            if pw:
                query("update users set name=%s, active=%s, password_hash=%s where id=%s",
                      (name, active, generate_password_hash(pw), uid))
            else:
                query("update users set name=%s, active=%s where id=%s", (name, active, uid))
            flash("Utilisateur mis à jour.")
            return redirect(url_for("admin_users"))
    pools_ = query("select p.id, p.name from pools p join pool_access a on a.pool_id=p.id "
                   "where a.user_id=%s order by p.name", (uid,))
    return render_template("admin_user.html", u=u, user_pools=pools_)


# ---------------------------------------------------------------- CLI
@app.cli.command("create-admin")
@click.argument("email")
@click.option("--name", default="Administrateur")
@click.password_option()
def create_admin(email, name, password):
    """Crée le premier compte administrateur."""
    with psycopg.connect(DSN) as c:
        c.execute("insert into users (email, name, password_hash, role) values (%s,%s,%s,'admin')",
                  (email.lower(), name, generate_password_hash(password)))
    click.echo("Administrateur créé.")


@app.cli.command("init-db")
def init_db():
    """Applique schema.sql."""
    with psycopg.connect(DSN) as c:
        c.execute(open(os.path.join(os.path.dirname(__file__), "schema.sql"), encoding="utf-8").read())
    click.echo("Schéma appliqué.")
