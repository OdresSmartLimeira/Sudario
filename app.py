
@app.route('/sales', methods=['GET', 'POST'])
@login_required
def sales():
    with db() as con:
        if request.method == 'POST':
            cid = request.form.get('client_id', type=int)
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
            user = con.execute(
                'SELECT * FROM users WHERE id=?',
                (owner,)
            ).fetchone()

            if not user:
                flash('Vendedor não encontrado.', 'error')
                return redirect(url_for('sales'))

            rate_row = con.execute(
                'SELECT rate FROM category_rates WHERE category=?',
                (category,)
            ).fetchone()

            if not rate_row:
                flash('Categoria inválida.', 'error')
                return redirect(url_for('sales'))

            rate = rate_row['rate']

            con.execute(
                '''INSERT INTO sales
                (client_id,user_id,category,description,
                 amount,rate,commission,created_at)
                VALUES(?,?,?,?,?,?,?,?)''',
                (
                    cid, owner, category,
                    request.form.get('description', '')[:200],
                    amount, rate,
                    round(amount * rate / 100, 2),
                    now()
                )
            )

            flash('Venda registrada.', 'ok')
            return redirect(url_for('sales'))

        clients = visible_clients(con)

        if current_user.role == 'admin':
            rows = con.execute(
                '''SELECT s.*, c.name AS client,
                   u.name AS seller
                   FROM sales s
                   JOIN clients c ON c.id=s.client_id
                   JOIN users u ON u.id=s.user_id
                   ORDER BY s.id DESC'''
            ).fetchall()
        else:
            rows = con.execute(
                '''SELECT s.*, c.name AS client,
                   u.name AS seller
                   FROM sales s
                   JOIN clients c ON c.id=s.client_id
                   JOIN users u ON u.id=s.user_id
                   WHERE s.user_id=?
                   ORDER BY s.id DESC''',
                (current_user.id,)
            ).fetchall()

        rates = con.execute(
            'SELECT * FROM category_rates'
        ).fetchall()

    return render_template(
        'sales.html',
        sales=rows,
        clients=clients,
        rates=rates
    )
