    return render_template('conversations.html', clients=rows, selected=selected, messages=messages, replies=replies)

@app.route('/replies', methods=['POST'])
@login_required
def replies():
    title = request.form.get('title', '').strip()[:80]
    body = request.form.get('body', '').strip()[:2000]
    if title and body:
        shared = request.form.get('shared') == '1' and current_user.role == 'admin'
        with db() as con:
            con.execute('INSERT INTO quick_replies(title,body,owner_id) VALUES(?,?,?)', (title, body, None if shared else current_user.id))
    return redirect(url_for('conversations'))

@app.route('/funnel', methods=['GET', 'POST'])
@login_required
def funnel():
    with db() as con:
        if request.method == 'POST':
            if current_user.role != 'admin':
                abort(403)
            name = request.form.get('name', '').strip()[:80]
            if name:
                con.execute('INSERT INTO stages(name,position) VALUES(?,?)', (name, con.execute('SELECT COALESCE(MAX(position),0)+1 FROM stages').fetchone()[0]))
            return redirect(url_for('funnel'))
        stages = con.execute('SELECT * FROM stages ORDER BY position').fetchall()
        clients = visible_clients(con)
    return render_template('funnel.html', stages=stages, clients=clients)

@app.route('/sales', methods=['GET', 'POST'])
@login_required
def sales():
    with db() as con:
        if request.method == 'POST':
            cid = form_int('client_id', 0)
            if not cid:
                flash('Selecione um cliente.', 'error')
                return redirect(url_for('sales'))
            c = get_client(con, cid)
            amount = amount_value(request.form.get('amount'))
            category = request.form.get('category', 'Celulares')
            if amount <= 0:
                flash('Valor inválido.', 'error')
                return redirect(url_for('sales'))
            owner = c['owner_id'] or current_user.id
            user = con.execute('SELECT * FROM users WHERE id=?', (owner,)).fetchone()
            if not user:
                flash('Vendedor não encontrado.', 'error')
                return redirect(url_for('sales'))
            rate_row = con.execute('SELECT rate FROM category_rates WHERE category=?', (category,)).fetchone()
            if not rate_row:
                flash('Categoria inválida.', 'error')
                return redirect(url_for('sales'))
            rate = rate_row['rate']
            con.execute('INSERT INTO sales(client_id,user_id,category,description,amount,rate,commission,created_at) VALUES(?,?,?,?,?,?,?,?)', (cid, owner, category, request.form.get('description', '')[:200], amount, rate, round(amount * rate / 100, 2), now()))
            flash('Venda registrada.', 'ok')
            return redirect(url_for('sales'))
        clients = visible_clients(con)
        sql = '''SELECT s.*,c.name AS client,u.name AS seller FROM sales s JOIN clients c ON c.id=s.client_id JOIN users u ON u.id=s.user_id'''
        if current_user.role == 'admin':
            rows = con.execute(sql + ' ORDER BY s.id DESC').fetchall()
        else:
            rows = con.execute(sql + ' WHERE s.user_id=? ORDER BY s.id DESC', (current_user.id,)).fetchall()
        rates = con.execute('SELECT * FROM category_rates').fetchall()
    return render_template('sales.html', sales=rows, clients=clients, rates=rates)

# Receptor de diagnóstico: armazena eventos autenticados sem alterar cadastros.
@app.route('/webhooks/orbitta', methods=['POST'])
@csrf.exempt
def orbitta_webhook():
    expected = os.environ.get('ORBITTA_WEBHOOK_TOKEN', '')
    if len(expected) < 32:
        app.logger.error('ORBITTA_WEBHOOK_TOKEN não configurado corretamente.')
        return jsonify(error='Webhook indisponível'), 503
    supplied = request.headers.get('X-Webhook-Token', '')
    if not supplied:
        supplied = request.args.get('token', '')
    if not hmac.compare_digest(supplied, expected):
        return jsonify(error='Não autorizado'), 401
    if not request.is_json:
        return jsonify(error='Envie JSON'), 415
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error='JSON deve ser um objeto'), 400
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()
    event_type = str(payload.get('event_type') or payload.get('type') or payload.get('event') or '')[:150]
    with db() as con:
        inserted = con.execute('''INSERT INTO orbitta_events(payload_hash,event_type,received_at,payload_json,processed)
                                  VALUES(?,?,?,?,0) ON CONFLICT(payload_hash) DO NOTHING RETURNING id''',
                               (digest, event_type, now(), raw)).fetchone()
    return jsonify(ok=True, duplicate=inserted is None), 200

@app.route('/admin/orbitta/events', methods=['GET'])
@admin_only
def orbitta_events():
    with db() as con:
        rows = con.execute('SELECT id,event_type,received_at,processed,payload_json FROM orbitta_events ORDER BY id DESC LIMIT 100').fetchall()
    return jsonify(events=[{'id': r['id'], 'event_type': r['event_type'], 'received_at': r['received_at'], 'processed': bool(r['processed']), 'payload': json.loads(r['payload_json'])} for r in rows])

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '5000')), debug=False)
