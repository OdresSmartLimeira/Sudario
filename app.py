import os
import csv
import io
import json
import hmac
import hashlib
import secrets
import logging
from datetime import datetime, date, timezone
from functools import wraps

import psycopg2
import psycopg2.extras
from psycopg2 import errors
from flask import Flask, render_template, request, redirect, url_for, flash, abort, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from openpyxl import load_workbook

load_dotenv()
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
secret = os.environ.get('SECRET_KEY')
if not secret:
    if os.environ.get('RENDER'):
        raise RuntimeError('Configure SECRET_KEY no Render.')
    secret = secrets.token_hex(32)
    app.logger.warning('SECRET_KEY temporária: configure uma chave persistente.')
app.config.update(
    SECRET_KEY=secret,
    MAX_CONTENT_LENGTH=3 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE', '1' if os.environ.get('RENDER') else '0') == '1',
)
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise RuntimeError('Configure DATABASE_URL no ambiente.')
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

SCHEMA_PG = '''
CREATE TABLE IF NOT EXISTS users(id SERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','staff')), commission_rate DOUBLE PRECISION NOT NULL DEFAULT 3);
CREATE TABLE IF NOT EXISTS stages(id SERIAL PRIMARY KEY, name TEXT NOT NULL, position INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS clients(id SERIAL PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL, interest TEXT DEFAULT '', owner_id INTEGER REFERENCES users(id), stage_id INTEGER REFERENCES stages(id), consent INTEGER NOT NULL DEFAULT 0, opted_out INTEGER NOT NULL DEFAULT 0, replied INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaigns(id SERIAL PRIMARY KEY, title TEXT NOT NULL, message TEXT NOT NULL, scheduled_at TEXT, creator_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'rascunho');
CREATE TABLE IF NOT EXISTS campaign_clients(campaign_id INTEGER NOT NULL REFERENCES campaigns(id), client_id INTEGER NOT NULL REFERENCES clients(id), PRIMARY KEY(campaign_id,client_id));
CREATE TABLE IF NOT EXISTS messages(id SERIAL PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), author_id INTEGER REFERENCES users(id), direction TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sales(id SERIAL PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), user_id INTEGER NOT NULL REFERENCES users(id), category TEXT NOT NULL, description TEXT NOT NULL, amount DOUBLE PRECISION NOT NULL, rate DOUBLE PRECISION NOT NULL, commission DOUBLE PRECISION NOT NULL, created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'concluida');
CREATE TABLE IF NOT EXISTS goals(id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id), month TEXT NOT NULL, amount DOUBLE PRECISION NOT NULL, UNIQUE(user_id,month));
CREATE TABLE IF NOT EXISTS category_rates(category TEXT PRIMARY KEY, rate DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS quick_replies(id SERIAL PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, owner_id INTEGER REFERENCES users(id));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS orbitta_events(id SERIAL PRIMARY KEY, payload_hash TEXT UNIQUE NOT NULL, event_type TEXT, received_at TEXT NOT NULL, payload_json TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0);
'''

class PgConn:
    def __init__(self):
        self.raw = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)

    def execute(self, sql, params=()):
        cur = self.raw.cursor()
        cur.execute(sql.replace('?', '%s'), params)
        return cur

    def executemany(self, sql, seq):
        cur = self.raw.cursor()
        cur.executemany(sql.replace('?', '%s'), seq)
        return cur

    def executescript(self, sql):
        cur = self.raw.cursor()
        cur.execute(sql)
        return cur

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type:
                self.raw.rollback()
            else:
                self.raw.commit()
        finally:
            self.raw.close()

def db():
    return PgConn()
