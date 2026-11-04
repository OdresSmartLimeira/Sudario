# Casa do Celular CRM — protótipo funcional (ambiente de testes)

Aplicação Flask com SQLite para testar o fluxo administrativo de clientes, campanhas simuladas, conversas simuladas, funil de vendas, vendas, metas e comissões.

**Não envia nem recebe mensagens reais pelo WhatsApp.** Não implementa conexão por QR Code, agendador de envios, notificações em tempo real, anexos, pagamentos de comissões, limites efetivos de envio nem hospedagem automática. Os dados de clientes inseridos são persistidos localmente no SQLite; use somente dados fictícios nesta versão.

## Rodar no computador

1. Instale Python 3.11+.
2. Copie `.env.example` para `.env` e defina `SECRET_KEY` (uma string aleatória longa), `ADMIN_EMAIL` e `ADMIN_PASSWORD` (12+ caracteres). Não publique `.env`.
3. No terminal, dentro da pasta do projeto:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

4. Acesse `http://127.0.0.1:5000` e faça login com as credenciais definidas no `.env`.
5. No menu **Usuários**, crie os três funcionários.

Para gerar uma chave segura: `python -c "import secrets; print(secrets.token_hex(32))"`.

## Arquivos e dados

- `app.py`: rotas, permissões e banco de dados SQLite.
- `templates/`: telas HTML.
- `static/style.css`: visual do painel.
- `requirements.txt`: dependências.
- `.env.example`: variáveis de ambiente sem segredos.
- `.gitignore`: impede commit acidental de `.env` e do banco SQLite.

## Permissões e regras implementadas

- Login com hash de senha e proteção CSRF.
- Administrador pode visualizar clientes de todos e gerenciar usuários.
- Funcionário acessa apenas clientes atribuídos e registra vendas próprias ou vinculadas aos clientes atribuídos.
- Importação CSV/XLSX e distribuição automática/manual para funcionários.
- Consentimento e descadastramento são registrados.
- Campanhas são salvas **somente como simulação**; clientes sem autorização, descadastrados ou que responderam são excluídos da seleção.
- Mensagens simuladas de entrada marcam o cliente como `replied`.
- Comissão por categoria prevalece sobre taxa geral; valores são gravados no momento da venda.

## Limitações antes de uso real

Este é um MVP de demonstração, não pronto para produção. Antes de usar dados reais ou publicar na internet: adicionar testes automatizados, política de privacidade/LGPD, trilha de auditoria, recuperação de senha, autenticação multifator, proteção contra tentativas repetidas de login, HTTPS, backups, armazenamento persistente gerenciado, migrações de banco, controle de concorrência, regras de envio por horário e limite, gestão de cancelamentos, segurança de uploads e revisão de permissões. Para uso hospedado, preferir PostgreSQL em vez de SQLite e configurar `COOKIE_SECURE=1` sob HTTPS.

A conexão não oficial ao WhatsApp Web via QR Code é uma proposta separada, não incluída; pode ser instável ou levar a restrições do número. Não há garantia de compatibilidade ou entrega.

## Publicar no GitHub

Crie um repositório privado e envie **somente os arquivos desta pasta**, sem `.env` ou `.db`. No GitHub: **Add file → Upload files**. Alternativamente, use Git local.

## Hospedagem

A aplicação pode ser executada por `gunicorn app:app`, com as variáveis de ambiente configuradas. **Não use SQLite em hospedagem gratuita com disco efêmero para dados importantes**: o banco pode desaparecer ao reiniciar. Não exponha esta versão diretamente à internet com informações reais de clientes.
