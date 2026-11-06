# Painel de Atendimento WhatsApp (estilo Orbitta)

Conversas, Leads e Agendamentos, com envio de **texto e áudio** pelo painel, usando a **API oficial da Meta (WhatsApp Cloud API)**.
Stack: Node.js + Express + PostgreSQL. Hospedagem: Render.

## 1. Subir no GitHub e no Render
1. Crie um repositório e envie estes arquivos (`git init`, `git add .`, `git commit`, `git push`).
2. No Render: **New > Blueprint**, escolha o repositório. O `render.yaml` cria o serviço web e o PostgreSQL.
3. Preencha as variáveis quando o Render pedir: `ADMIN_PASS` (senha do painel). `WA_TOKEN`, `WA_PHONE_ID` e `APP_SECRET` você preenche depois (passo 2).
4. Anote a URL final, ex.: `https://whatsapp-crm.onrender.com`.

> Plano gratuito do Render "dorme" e o banco gratuito expira em 30 dias. Para atendimento real use o plano pago (o `render.yaml` já usa Starter).

## 2. Vincular o WhatsApp Business (API da Meta)
1. Acesse developers.facebook.com > **Meus apps > Criar app** > tipo **Empresa** > adicione o produto **WhatsApp**.
2. Em **WhatsApp > Configuração da API**:
   - Clique em **Adicionar número de telefone** e informe o número da empresa. Ele será verificado por SMS/ligação.
   - O número **não pode estar ativo no app WhatsApp comum** (ou Business app) nem em outra plataforma como a Orbitta. Ao migrar, a Orbitta deixa de receber as mensagens dele.
   - Copie o **ID do número de telefone** -> variável `WA_PHONE_ID` no Render.
3. **Token permanente** (o temporário expira em 24h): business.facebook.com > Configurações > **Usuários do sistema** > crie um usuário administrador > **Gerar token** com as permissões `whatsapp_business_messaging` e `whatsapp_business_management` -> variável `WA_TOKEN`.
4. **Chave secreta do app** (Configurações do app > Básico > Chave secreta) -> variável `APP_SECRET` (valida que o webhook veio da Meta).
5. **Webhook**: em WhatsApp > Configuração > Webhook, clique em Editar:
   - URL de callback: `https://SEU-APP.onrender.com/webhook`
   - Token de verificação: o valor da variável `WA_VERIFY_TOKEN` (o Render gerou; veja em Environment).
   - Depois de verificar, assine o campo **messages**.
6. Faça **Deploy** de novo no Render e mande uma mensagem para o número: ela aparece em **Conversas**.

## 3. Regras do WhatsApp que você precisa saber
- Você só pode enviar mensagem livre (texto/áudio) até **24h depois da última mensagem do cliente**. O painel avisa quando passou.
- Para iniciar conversa ou fazer **disparos em massa** é preciso **modelo de mensagem (template) aprovado** pela Meta e clientes que aceitaram receber contato. É isso que evita bloqueio do número. A aba Campanhas é o próximo passo.
- Áudios: o navegador grava em webm/mp4; o servidor converte para ogg/opus com ffmpeg (já incluso via `ffmpeg-static`) porque o WhatsApp só aceita esse formato como mensagem de voz.

## 4. Rodar localmente
```
npm install
export DATABASE_URL=postgres://usuario:senha@localhost:5432/crm
export ADMIN_PASS=minhasenha WA_TOKEN=... WA_PHONE_ID=...
npm start   # http://localhost:3000
```
Para testar o webhook local use um túnel (ex.: ngrok) e coloque a URL dele no passo 2.5.

## 5. Estrutura
- `server.js`: API, webhook, envio de texto/áudio, banco (tabelas criadas automaticamente).
- `public/index.html`: painel (login, Conversas, Leads, Agendamentos).
- `render.yaml`: configuração do Render.
