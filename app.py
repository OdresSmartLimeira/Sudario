import os, sqlite3, csv, io, secrets
from datetime import datetime, date
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, abort, Response
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from openpyxl import load_workbook

load_dotenv()
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.config['MAX_CONTENT_LENGTH'] = 3 * 1024 * 1024
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('COOKIE_SECURE') == '1'
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
DB = os.environ.get('DATABASE_PATH', 'crm.sqlite3')

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','staff')), commission_rate REAL NOT NULL DEFAULT 3);
CREATE TABLE IF NOT EXISTS stages(id INTEGER PRIMARY KEY, name TEXT NOT NULL, position INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL, interest TEXT DEFAULT '', owner_id INTEGER REFERENCES users(id), stage_id INTEGER REFERENCES stages(id), consent INTEGER NOT NULL DEFAULT 0, opted_out INTEGER NOT NULL DEFAULT 0, replied INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaigns(id INTEGER PRIMARY KEY, title TEXT NOT NULL, message TEXT NOT NULL, scheduled_at TEXT, creator_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'rascunho');
CREATE TABLE IF NOT EXISTS campaign_clients(campaign_id INTEGER NOT NULL REFERENCES campaigns(id), client_id INTEGER NOT NULL REFERENCES clients(id), PRIMARY KEY(campaign_id,client_id));
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), author_id INTEGER REFERENCES users(id), direction TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sales(id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), user_id INTEGER NOT NULL REFERENCES users(id), category TEXT NOT NULL, description TEXT NOT NULL, amount REAL NOT NULL, rate REAL NOT NULL, commission REAL NOT NULL, created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'concluida');
CREATE TABLE IF NOT EXISTS goals(id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), month TEXT NOT NULL, amount REAL NOT NULL, UNIQUE(user_id,month));
CREATE TABLE IF NOT EXISTS category_rates(category TEXT PRIMARY KEY, rate REAL NOT NULL);
CREATE TABLE IF NOT EXISTS quick_replies(id INTEGER PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, owner_id INTEGER REFERENCES users(id));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
'''

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    return con

def init_db():
    with db() as con:
        con.executescript(SCHEMA)
        if not con.execute('SELECT 1 FROM stages').fetchone():
            con.executemany('INSERT INTO stages(name,position) VALUES(?,?)', [(s,i) for i,s in enumerate(['Novo cliente','Em atendimento','Negociação','Venda realizada','Perdido'],1)])
        if not con.execute('SELECT 1 FROM category_rates').fetchone():
            con.executemany('INSERT INTO category_rates(category,rate) VALUES(?,?)',[('Celulares',3),('Acessórios',5),('Serviços',7)])
        if not con.execute('SELECT 1 FROM users').fetchone():
            email = os.environ.get('ADMIN_EMAIL')
            password = os.environ.get('ADMIN_PASSWORD')
            if email and password and len(password)>=12:
                con.execute('INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)',('Administrador',email.strip().lower(),generate_password_hash(password),'admin'))
            else:
                print('Configure ADMIN_EMAIL e ADMIN_PASSWORD (12+ caracteres) no .env para criar o primeiro administrador.')

class User(UserMixin):
    def __init__(self, row): self.id=row['id']; self.name=row['name']; self.email=row['email']; self.role=row['role']
@login_manager.user_loader
def load_user(uid):
    with db() as con: row=con.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    return User(row) if row else None

def admin_only(fn):
    @wraps(fn)
    @login_required
    def inner(*args,**kwargs):
        if current_user.role!='admin': abort(403)
        return fn(*args,**kwargs)
    return inner

def visible_clients(con):
    if current_user.role=='admin': return con.execute('SELECT c.*,u.name owner,s.name stage FROM clients c LEFT JOIN users u ON c.owner_id=u.id LEFT JOIN stages s ON c.stage_id=s.id ORDER BY c.id DESC').fetchall()
    return con.execute('SELECT c.*,u.name owner,s.name stage FROM clients c LEFT JOIN users u ON c.owner_id=u.id LEFT JOIN stages s ON c.stage_id=s.id WHERE c.owner_id=? ORDER BY c.id DESC',(current_user.id,)).fetchall()

def get_client(con,cid):
    c=con.execute('SELECT * FROM clients WHERE id=?',(cid,)).fetchone()
    if not c or (current_user.role!='admin' and c['owner_id']!=current_user.id): abort(404)
    return c

def now(): return datetime.now().isoformat(timespec='seconds')
def amount_value(raw):
    try: return round(float(str(raw).replace(',','.')),2)
    except (ValueError,TypeError): return -1

@app.template_filter('brl')
def brl(value): return 'R$ {:,.2f}'.format(value or 0).replace(',','X').replace('.',',').replace('X','.')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        with db() as con: row=con.execute('SELECT * FROM users WHERE email=?',(request.form.get('email','').strip().lower(),)).fetchone()
        if row and check_password_hash(row['password_hash'],request.form.get('password','')):
            login_user(User(row)); return redirect(url_for('dashboard'))
        flash('E-mail ou senha inválidos.','error')
    return render_template('login.html')

@app.route('/logout',methods=['POST'])
@login_required
def logout(): logout_user(); return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    with db() as con:
        clients=visible_clients(con)
        if current_user.role=='admin':
            sales=con.execute("SELECT * FROM sales WHERE status='concluida'").fetchall()
            campaigns=con.execute('SELECT * FROM campaigns ORDER BY id DESC LIMIT 6').fetchall()
        else:
            sales=con.execute("SELECT * FROM sales WHERE user_id=? AND status='concluida'",(current_user.id,)).fetchall()
            campaigns=con.execute('SELECT * FROM campaigns WHERE creator_id=? ORDER BY id DESC LIMIT 6',(current_user.id,)).fetchall()
    month=date.today().strftime('%Y-%m')
    return render_template('dashboard.html',clients=clients,sales=sales,campaigns=campaigns,month=month)

@app.route('/clients',methods=['GET','POST'])
@login_required
def clients():
    with db() as con:
        if request.method=='POST':
            name=request.form.get('name','').strip()[:120]; phone=request.form.get('phone','').strip()[:40]
            if not name or not phone: flash('Nome e telefone são obrigatórios.','error')
            else:
                owner=int(request.form.get('owner_id') or current_user.id) if current_user.role=='admin' else current_user.id
                if not con.execute("SELECT 1 FROM users WHERE id=? AND role='staff'",(owner,)).fetchone(): owner=current_user.id
                stage=con.execute('SELECT id FROM stages ORDER BY position LIMIT 1').fetchone()['id']
                con.execute('INSERT INTO clients(name,phone,interest,owner_id,stage_id,consent,created_at) VALUES(?,?,?,?,?,?,?)',(name,phone,request.form.get('interest','')[:200],owner,stage,int('consent' in request.form),now()))
                flash('Cliente cadastrado.','ok')
            return redirect(url_for('clients'))
        rows=visible_clients(con); users=con.execute("SELECT id,name FROM users WHERE role='staff' ORDER BY name").fetchall(); stages=con.execute('SELECT * FROM stages ORDER BY position').fetchall()
    return render_template('clients.html',clients=rows,users=users,stages=stages)

@app.route('/clients/<int:cid>/update',methods=['POST'])
@login_required
def update_client(cid):
    with db() as con:
        c=get_client(con,cid)
        stage=int(request.form.get('stage_id') or c['stage_id'])
        if not con.execute('SELECT 1 FROM stages WHERE id=?',(stage,)).fetchone(): abort(400)
        owner=c['owner_id']
        if current_user.role=='admin' and request.form.get('owner_id'):
            owner=int(request.form['owner_id'])
            if not con.execute('SELECT 1 FROM users WHERE id=?',(owner,)).fetchone(): abort(400)
        con.execute('UPDATE clients SET stage_id=?,owner_id=?,consent=?,opted_out=? WHERE id=?',(stage,owner,int('consent' in request.form),int('opted_out' in request.form),cid))
    return redirect(url_for('clients'))

@app.route('/clients/import',methods=['POST'])
@login_required
def import_clients():
    upload=request.files.get('file')
    if not upload or not upload.filename: flash('Selecione um arquivo CSV ou XLSX.','error'); return redirect(url_for('clients'))
    extension=secure_filename(upload.filename).lower().rsplit('.',1)[-1]
    if extension not in ('csv','xlsx'): abort(400)
    try:
        if extension=='csv':
            data=upload.read().decode('utf-8-sig'); reader=csv.DictReader(io.StringIO(data)); records=list(reader)
        else:
            wb=load_workbook(upload,read_only=True,data_only=True); sheet=wb.active; values=sheet.iter_rows(values_only=True); headers=[str(v or '').strip().lower() for v in next(values)]; records=[dict(zip(headers,row)) for row in values]
    except Exception: flash('Arquivo inválido.','error'); return redirect(url_for('clients'))
    if len(records)>3000: flash('Máximo de 3000 registros por importação.','error'); return redirect(url_for('clients'))
    with db() as con:
        staff=con.execute("SELECT id FROM users WHERE role='staff' ORDER BY id").fetchall()
        stage=con.execute('SELECT id FROM stages ORDER BY position LIMIT 1').fetchone()['id']
        method=request.form.get('distribution','manual'); chosen=request.form.get('owner_id')
        added=0
        for rec in records:
            rec={str(k).strip().lower():v for k,v in rec.items() if k is not None}
            name=str(rec.get('nome') or rec.get('name') or '').strip()[:120]; phone=str(rec.get('telefone') or rec.get('phone') or '').strip()[:40]
            if not name or not phone: continue
            if current_user.role!='admin': owner=current_user.id
            elif method=='automatic' and staff: owner=staff[added%len(staff)]['id']
            elif chosen and con.execute('SELECT 1 FROM users WHERE id=?',(chosen,)).fetchone(): owner=int(chosen)
            else: owner=current_user.id
            consent=str(rec.get('autorizacao') or rec.get('consentimento') or '').strip().lower() in ('sim','s','1','true','yes')
            con.execute('INSERT INTO clients(name,phone,interest,owner_id,stage_id,consent,created_at) VALUES(?,?,?,?,?,?,?)',(name,phone,str(rec.get('interesse') or '')[:200],owner,stage,int(consent),now())); added+=1
    flash(f'{added} clientes importados.','ok'); return redirect(url_for('clients'))

@app.route('/campaigns',methods=['GET','POST'])
@login_required
def campaigns():
    with db() as con:
        if request.method=='POST':
            title=request.form.get('title','').strip()[:120]; msg=request.form.get('message','').strip()[:2000]
            if not title or not msg: flash('Preencha título e mensagem.','error')
            else:
                con.execute('INSERT INTO campaigns(title,message,scheduled_at,creator_id,created_at,status) VALUES(?,?,?,?,?,?)',(title,msg,request.form.get('scheduled_at','')[:30],current_user.id,now(),'simulacao'))
                campaign_id=con.execute('SELECT last_insert_rowid()').fetchone()[0]
                eligible=[c for c in visible_clients(con) if c['consent'] and not c['opted_out'] and not c['replied']]
                con.executemany('INSERT INTO campaign_clients(campaign_id,client_id) VALUES(?,?)',[(campaign_id,c['id']) for c in eligible])
                flash(f'Campanha salva em modo simulação para {len(eligible)} contatos elegíveis. Nenhuma mensagem foi enviada.','ok')
            return redirect(url_for('campaigns'))
        if current_user.role=='admin': rows=con.execute('SELECT ca.*,u.name creator,(SELECT COUNT(*) FROM campaign_clients cc WHERE cc.campaign_id=ca.id) recipients FROM campaigns ca JOIN users u ON ca.creator_id=u.id ORDER BY ca.id DESC').fetchall()
        else: rows=con.execute('SELECT ca.*,u.name creator,(SELECT COUNT(*) FROM campaign_clients cc WHERE cc.campaign_id=ca.id) recipients FROM campaigns ca JOIN users u ON ca.creator_id=u.id WHERE ca.creator_id=? ORDER BY ca.id DESC',(current_user.id,)).fetchall()
    return render_template('campaigns.html',campaigns=rows)

@app.route('/conversations',methods=['GET','POST'])
@login_required
def conversations():
    with db() as con:
        rows=visible_clients(con); selected=request.args.get('client',type=int)
        if selected: get_client(con,selected)
        elif rows: selected=rows[0]['id']
        if request.method=='POST':
            selected=int(request.form.get('client_id','0')); get_client(con,selected)
            body=request.form.get('body','').strip()[:3000]; direction=request.form.get('direction','out')
            if body and direction in ('in','out'):
                con.execute('INSERT INTO messages(client_id,author_id,direction,content,created_at) VALUES(?,?,?,?,?)',(selected,current_user.id,direction,body,now()))
                if direction=='in': con.execute('UPDATE clients SET replied=1 WHERE id=?',(selected,))
                flash('Mensagem registrada na simulação. Não foi enviada pelo WhatsApp.','ok')
            return redirect(url_for('conversations',client=selected))
        messages=con.execute('SELECT * FROM messages WHERE client_id=? ORDER BY id',(selected,)).fetchall() if selected else []
        replies=con.execute('SELECT * FROM quick_replies WHERE owner_id IS NULL OR owner_id=? ORDER BY id',(current_user.id,)).fetchall()
    return render_template('conversations.html',clients=rows,selected=selected,messages=messages,replies=replies)

@app.route('/replies',methods=['POST'])
@login_required
def replies():
    title=request.form.get('title','').strip()[:80]; body=request.form.get('body','').strip()[:2000]
    if title and body:
        shared=request.form.get('shared')=='1' and current_user.role=='admin'
        with db() as con: con.execute('INSERT INTO quick_replies(title,body,owner_id) VALUES(?,?,?)',(title,body,None if shared else current_user.id))
    return redirect(url_for('conversations'))

@app.route('/funnel',methods=['GET','POST'])
@login_required
def funnel():
    with db() as con:
        if request.method=='POST':
            if current_user.role!='admin': abort(403)
            name=request.form.get('name','').strip()[:80]
            if name: con.execute('INSERT INTO stages(name,position) VALUES(?,?)',(name,con.execute('SELECT COALESCE(MAX(position),0)+1 FROM stages').fetchone()[0]))
            return redirect(url_for('funnel'))
        stages=con.execute('SELECT * FROM stages ORDER BY position').fetchall(); clients=visible_clients(con)
    return render_template('funnel.html',stages=stages,clients=clients)

@app.route('/sales',methods=['GET','POST'])
@login_required
def sales():
    with db() as con:
        if request.method=='POST':
            cid=int(request.form.get('client_id') or 0); c=get_client(con,cid)
            amount=amount_value(request.form.get('amount')); category=request.form.get('category','Celulares')
            if amount<=0: flash('Valor inválido.','error'); return redirect(url_for('sales'))
            owner=c['owner_id'] or current_user.id
            user=con.execute('SELECT * FROM users WHERE id=?',(owner,)).fetchone()
            rate_row=con.execute('SELECT rate FROM category_rates WHERE category=?',(category,)).fetchone()
            rate=rate_row['rate'] if rate_row else (user['commission_rate'] if user else 0)
            con.execute('INSERT INTO sales(client_id,user_id,category,description,amount,rate,commission,created_at) VALUES(?,?,?,?,?,?,?,?)',(cid,owner,category,request.form.get('description','')[:200],amount,rate,round(amount*rate/100,2),now()))
            flash('Venda registrada.','ok'); return redirect(url_for('sales'))
        clients=visible_clients(con)
        if current_user.role=='admin': rows=con.execute('SELECT s.*,c.name client,u.name seller FROM sales s JOIN clients c ON c.id=s.client_id JOIN users u ON u.id=s.user_id ORDER BY s.id DESC').fetchall()
        else: rows=con.execute('SELECT s.*,c.name client,u.name seller FROM sales s JOIN clients c ON c.id=s.client_id JOIN users u ON u.id=s.user_id WHERE s.user_id=? ORDER BY s.id DESC',(current_user.id,)).fetchall()
        rates=con.execute('SELECT * FROM category_rates').fetchall()
    return render_template('sales.html',sales=rows,clients=clients,rates=rates)

@app.route('/goals',methods=['GET','POST'])
@login_required
def goals():
    month=request.values.get('month') or date.today().strftime('%Y-%m')
    if len(month)!=7 or month[4]!='-': abort(400)
    with db() as con:
        if request.method=='POST':
            if current_user.role!='admin': abort(403)
            amount=amount_value(request.form.get('amount')); uid=request.form.get('user_id')
            if amount>=0:
                if uid=='store':
                    con.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(f'goal:{month}',str(amount)))
                else:
                    con.execute('INSERT INTO goals(user_id,month,amount) VALUES(?,?,?) ON CONFLICT(user_id,month) DO UPDATE SET amount=excluded.amount',(int(uid),month,amount))
            return redirect(url_for('goals',month=month))
        users=con.execute("SELECT * FROM users WHERE role='staff' ORDER BY name").fetchall() if current_user.role=='admin' else con.execute('SELECT * FROM users WHERE id=?',(current_user.id,)).fetchall()
        rows=[]
        for u in users:
            goal=con.execute('SELECT amount FROM goals WHERE user_id=? AND month=?',(u['id'],month)).fetchone()
            sold=con.execute("SELECT COALESCE(SUM(amount),0) v,COALESCE(SUM(commission),0) commission FROM sales WHERE user_id=? AND substr(created_at,1,7)=? AND status='concluida'",(u['id'],month)).fetchone()
            rows.append({'id':u['id'],'name':u['name'],'goal':goal['amount'] if goal else 0,'sold':sold['v'],'commission':sold['commission']})
        store=con.execute('SELECT value FROM settings WHERE key=?',(f'goal:{month}',)).fetchone()
    return render_template('goals.html',rows=rows,month=month,store_goal=float(store['value']) if store else 0)

@app.route('/users',methods=['GET','POST'])
@admin_only
def users():
    with db() as con:
        if request.method=='POST':
            name=request.form.get('name','').strip()[:100]; email=request.form.get('email','').strip().lower()[:180]; password=request.form.get('password',''); role=request.form.get('role')
            if name and email and len(password)>=12 and role in ('admin','staff'):
                try: con.execute('INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)',(name,email,generate_password_hash(password),role)); flash('Usuário criado.','ok')
                except sqlite3.IntegrityError: flash('E-mail já cadastrado.','error')
            else: flash('Informe nome, e-mail, perfil e senha de 12+ caracteres.','error')
            return redirect(url_for('users'))
        rows=con.execute('SELECT id,name,email,role,commission_rate FROM users ORDER BY id').fetchall()
    return render_template('users.html',users=rows)

@app.route('/users/<int:uid>/rate',methods=['POST'])
@admin_only
def user_rate(uid):
    rate=amount_value(request.form.get('rate'))
    if 0<=rate<=100:
        with db() as con: con.execute('UPDATE users SET commission_rate=? WHERE id=?',(rate,uid))
    return redirect(url_for('users'))

@app.route('/categories/rate',methods=['POST'])
@admin_only
def category_rate():
    rate=amount_value(request.form.get('rate')); category=request.form.get('category','')
    if 0<=rate<=100 and category in ('Celulares','Acessórios','Serviços'):
        with db() as con: con.execute('UPDATE category_rates SET rate=? WHERE category=?',(rate,category))
    return redirect(url_for('sales'))

@app.route('/settings')
@admin_only
def settings(): return render_template('settings.html')

@app.route('/health')
def health(): return {'status':'ok'}

init_db()
if __name__=='__main__': app.run(debug=False)
