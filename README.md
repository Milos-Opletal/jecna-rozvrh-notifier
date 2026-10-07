# jecna-rozvrh-notifier

Docker kontejner pro automatické monitorování mimořádného rozvrhu (suplování) pro zvolenou třídu ze SPŠE Ječná.

V nastaveném intervalu kontroluje změny rozvrhu (nová suplování, změny hodin, učeben, odpadlé hodiny či celodenní oznámení) a při detekci změn odesílá upozornění přes nakonfigurované webhooky.

---

## Funkce

- **Pravidelná kontrola**: Automatické dotazování v nastavitelném intervalu (výchozí 15 minut).
- **Bez přihlašovacích údajů**: Nevyžaduje heslo, konfiguruje se pouze název sledované třídy (`CLASS_NAME=C4b`).
- **Perzistentní stav**: Ukládání historie do `/data/state.json`, notifikace se posílají pouze při zjištění nových změn.
- **Souhrn v notifikaci**: Při zjištění změny posílá kompletní přehled aktuálních suplování dané třídy.
- **Ranní souhrnná notifikace**: Možnost odeslání ranního přehledu v určený čas s volbou cílových služeb.
- **Podpora webhooků**:
  - Home Assistant
  - Discord (včetně volitelného odděleného webhooku pro ranní souhrn)
  - Telegram Bot
  - ntfy.sh
  - Slack
  - Obecný HTTP JSON webhook
- **Podpora Dockeru a Portaineru**: Připraveno pro spuštění přes Docker Compose nebo Portainer Git stack.

---

## Nasazení v Portaineru

Portainer umožňuje nasadit stack přímo z Git repozitáře a volitelně jej automaticky aktualizovat při změnách ve větvi `main`.

### Postup nastavení:

1. V Portaineru přejděte do **Stacks** -> **Add stack**.
2. Zvolte metodu **Repository**.
3. Vyplňte parametry:
   - **Name:** `jecna-rozvrh-notifier`
   - **Repository URL:** URL repozitáře
   - **Repository reference:** `refs/heads/main`
   - **Compose path:** `docker-compose.yml`
   - **Authentication:** V případě privátního repozitáře zadejte uživatelské jméno a Personal Access Token (PAT).
4. Volitelně zapněte **Automatic updates** (Polling nebo Webhook).
5. V sekci **Environment variables** nastavte požadované proměnné (viz tabulka níže), minimálně:
   - `CLASS_NAME`: např. `C4b`
   - `CHECK_INTERVAL_SECONDS`: `900`
   - `TZ`: `Europe/Prague`
   - Alespoň jednu webhook URL (např. `HOMEASSISTANT_WEBHOOK_URL`, `DISCORD_WEBHOOK_URL`, `NTFY_URL`).
6. Klikněte na **Deploy the stack**.

---

## Spuštění přes Docker Compose (CLI)

```bash
# 1. Klonování repozitáře
git clone https://github.com/<uzivatel>/jecna-rozvrh-notifier.git
cd jecna-rozvrh-notifier

# 2. Vytvoření konfigurace
cp .env.example .env
nano .env

# 3. Spuštění kontejneru na pozadí
docker compose up -d --build
```

Sledování logů:
```bash
docker logs -f jecna-rozvrh-notifier
```

---

## Konfigurace webhooků

### 1. Home Assistant

Přidejte následující automatizaci do `automations.yaml` (nebo vytvořte novou přes UI se spouštěčem typu Webhook):

```yaml
alias: "Ječná - Upozornění na suplování"
description: "Přijme změnu z jecna-rozvrh-notifier a pošle notifikaci na mobil"
trigger:
  - platform: webhook
    webhook_id: "jecna_supl_webhook"
    allowed_methods:
      - POST
    local_only: false
action:
  - action: notify.notify
    data:
      title: "{{ trigger.json.title }}"
      message: "{{ trigger.json.message }}"
      data:
        priority: "high"
        tag: "jecna_supl"
        channel: "Mimořádný rozvrh"
mode: single
```

V `.env` nastavte:
```env
HOMEASSISTANT_WEBHOOK_URL=http://<IP_HOME_ASSISTANT>:8123/api/webhook/jecna_supl_webhook
```

---

### 2. Discord

1. V nastavení kanálu na Discordu přejděte do **Integrace** -> **Webhooky** -> **Vytvořit webhook**.
2. Zkopírujte URL webhooku a nastavte ji v `.env`:
   ```env
   DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
   ```

3. **Oddělený webhook pro ranní notifikaci (volitelné):**
   Pokud má ranní přehled směřovat do jiného kanálu než průběžná upozornění:
   ```env
   MORNING_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
   ```
   Pokud není nastavena, použije se výchozí `DISCORD_WEBHOOK_URL`.

---

### 3. ntfy.sh

Pro push notifikace na mobil přes službu ntfy:
1. Nainstalujte aplikaci ntfy na Android nebo iOS.
2. Přihlaste se k odběru libovolného vlastního tématu (např. `jecna_supl_notifikace`).
3. V `.env` nastavte:
   ```env
   NTFY_URL=https://ntfy.sh/jecna_supl_notifikace
   ```

---

### 4. Telegram Bot

1. Vytvořte bota přes `@BotFather` a získejte token.
2. Zjistěte ID cílového chatu (`CHAT_ID`).
3. V `.env` nastavte:
   ```env
   TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
   TELEGRAM_CHAT_ID=987654321
   ```

---

## Ranní souhrnná notifikace

Kontejner umožňuje odesílat ranní souhrn rozvrhu na daný den ve stanovený čas. Lze určit, do kterých služeb má ranní notifikace směřovat.

Příklad konfigurace v `.env`:
```env
MORNING_NOTIFICATION_ENABLED=true
MORNING_NOTIFICATION_TIME=07:00
MORNING_NOTIFICATION_TARGETS=all
MORNING_NOTIFICATION_ONLY_IF_CHANGES=true
```

### Parametry:

- `MORNING_NOTIFICATION_ENABLED`: Povolení ranního souhrnu (`true` / `false`, výchozí: `true`).
- `MORNING_NOTIFICATION_TIME`: Čas odeslání ve formátu `HH:MM` (výchozí: `07:00`).
- `MORNING_NOTIFICATION_TARGETS`: Cílové služby (výchozí: `all`). Podporované hodnoty lze kombinovat oddělením čárkou:
  - `all` / `*`: všechny nakonfigurované webhooky
  - `ha`, `haos`, `homeassistant`: Home Assistant
  - `discord`: Discord
  - `telegram`, `tg`: Telegram
  - `ntfy`: ntfy.sh
  - `slack`: Slack
  - `generic`: obecný JSON webhook
- `MORNING_NOTIFICATION_ONLY_IF_CHANGES`:
  - `true` (výchozí): Odešle se pouze v případě, že jsou pro daný den evidovány změny rozvrhu.
  - `false`: Odešle se každé ráno i v případě, že platí stálý rozvrh.

### Časové pásmo kontejneru

Pro správné načasování ranní notifikace kontejner využívá proměnnou `TZ`:
- Výchozí hodnota je `TZ=Europe/Prague` (středoevropský čas s automatickým přechodem CET/CEST).
- Při startu kontejner vypisuje detekovaný čas a pásmo do logu:
  ```text
  Container local time: 2026-09-25 09:16:08 (CEST, UTC+0200)
  ```

---

## Proměnné prostředí

| Proměnná | Výchozí hodnota | Popis |
|---|---|---|
| `TZ` | `Europe/Prague` | Časové pásmo kontejneru |
| `CHECK_INTERVAL_SECONDS` | `900` | Interval kontroly rozvrhu v sekundách |
| `CLASS_NAME` | `C4b` | Sledovaná třída (např. `C4b`, `A2a`) |
| `ALERT_ON_STARTUP` | `false` | Zda odeslat notifikace o existujících změnách při prvním spuštění |
| `REPEAT_ALL_CHANGES` | `true` | Při detekci změny zahrnout do notifikace přehled všech platných suplování |
| `MORNING_NOTIFICATION_ENABLED` | `true` | Povolení ranní souhrnné notifikace |
| `MORNING_NOTIFICATION_TIME` | `07:00` | Čas ranní notifikace (`HH:MM`) |
| `MORNING_NOTIFICATION_TARGETS` | `all` | Cílové služby pro ranní notifikaci |
| `MORNING_NOTIFICATION_ONLY_IF_CHANGES` | `true` | Odeslat ranní notifikaci pouze při existenci změn |
| `SUBSTITUTION_API_URL` | `https://jecnarozvrh.jzitnik.dev/versioned/v3` | Endpoint API pro mimořádný rozvrh |
| `STATE_FILE_PATH` | `/data/state.json` | Cesta k souboru s historií změn |
| `HOMEASSISTANT_WEBHOOK_URL` | `""` | URL webhooku Home Assistant |
| `DISCORD_WEBHOOK_URL` | `""` | URL výchozího Discord webhooku |
| `MORNING_DISCORD_WEBHOOK_URL` | `""` | URL Discord webhooku pro ranní notifikace |
| `TELEGRAM_BOT_TOKEN` | `""` | Token Telegram bota |
| `TELEGRAM_CHAT_ID` | `""` | ID chatu v Telegramu |
| `NTFY_URL` | `""` | URL tématu v ntfy.sh |
| `SLACK_WEBHOOK_URL` | `""` | URL Slack webhooku |
| `GENERIC_WEBHOOK_URL` | `""` | URL obecného JSON webhooku |

---

## Struktura projektu

```
jecna-rozvrh-notifier/
├── .github/
│   └── workflows/
│       └── docker-publish.yml
├── main.py
├── jecna.py
├── webhooks.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

---

## Poděkování

- [@jzitnik-dev](https://github.com/jzitnik-dev) – API pro rozvrh a suplování [jecnarozvrh.jzitnik.dev](https://jecnarozvrh.jzitnik.dev/)
- [@tomhula](https://github.com/tomhula) – [JecnaMobile](https://github.com/tomhula/JecnaMobile)

---

## Licence

Tento projekt je licencován pod licencí MIT.
