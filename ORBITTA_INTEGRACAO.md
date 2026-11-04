# Integração Orbitta — etapa 1 (diagnóstico seguro)

Este projeto adiciona `POST /webhooks/orbitta` e `GET /admin/orbitta/events`.
O receptor guarda eventos JSON em `orbitta_events`, sem modificar clientes, mensagens ou campanhas.

## Render

1. Faça backup dos dados e publique estes arquivos no repositório.
2. Em Render > Environment, crie `ORBITTA_WEBHOOK_TOKEN` com um valor aleatório de **pelo menos 32 caracteres**. Guarde-o em segredo.
3. A URL para configurar no Orbitta é `https://sudario.onrender.com/webhooks/orbitta?token=SEU_TOKEN`. Substitua `SEU_TOKEN` apenas no painel do Orbitta, nunca no GitHub nem nesta conversa.
4. Marque **Mensagens Recebidas**, **Conversas Atualizadas** e **Contatos Atualizados**, salve e use **Testar Webhook**.
5. Entre no CRM como administrador e abra `/admin/orbitta/events` para verificar o recebimento. Não envie conteúdo de mensagens nem tokens ao suporte/chat.

## Limitações e segurança

- O formato dos eventos e o método de autenticação nativo do Orbitta ainda são desconhecidos. A autenticação por token na URL é provisória e pode constar em logs; o ideal é usar assinatura HMAC em cabeçalho ou autenticação oficial documentada pelo Orbitta.
- O teste do Orbitta pode exigir um método diferente de autenticação ou não aceitar query strings. Nesse caso, NÃO remova a autenticação; consulte a documentação do Orbitta.
- A deduplicação por hash do JSON evita cópias idênticas, mas eventos legítimos repetidos com payload idêntico também serão tratados como duplicatas.
- Os dados armazenados podem conter informações pessoais. Restrinja o acesso, estabeleça retenção, obtenha consentimento adequado e não use dados reais em SQLite efêmero da Render Free.
- **Não há sincronização bidirecional, envio de WhatsApp ou processamento automático de respostas nesta etapa.** Isso depende da documentação da API e dos eventos do Orbitta.
- `ORBITTA_WEBHOOK_TOKEN` é uma variável nova; mantenha `SECRET_KEY`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` e outras configurações existentes.
