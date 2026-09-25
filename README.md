# Ječná Mimořádný Rozvrh Notifier 🔔

Samostatný, lehký Docker kontejner, který každých **15 minut** (nebo dle nastavení) automaticky monitoruje **mimořádný rozvrh (suplování)** pro třídu studenta ze **SPŠE Ječná**.

Při zjištění nové změny (přidání suplování, změna hodiny/učebny, odpadnutí hodiny, celodenní poznámka nebo oznámení) okamžitě odešle upozornění přes nakonfigurované webhooky.

---

## 🚀 Hlavní funkce

- ⏱️ **Kontrola každých 15 minut** (přesně odpovídá požadavku a intervalu aktualizací školy).
- 🎓 **Bezpečné a bez přihlašování** – **nejsou potřeba žádné přihlašovací údaje ani heslo**, stačí zadat sledovanou třídu (`CLASS_NAME=C4b`).
- 💾 **Perzistentní stav** v `/data/state.json` – upozorňuje pouze na skutečně **nové** změny (žádný spam při restartu či aktualizaci).
- 📋 **Kompletní přehled v každé notifikaci** – při zjištění nové změny zopakuje všechna aktuální suplování pro třídu, takže vidíte ucelený stav rozvrhu.
- ☀️ **Volitelná ranní notifikace** – možnost nastavit si ranní souhrn (např. v 07:00) a vybrat, na které webhooky má dorazit (např. pouze Home Assistant nebo Home Assistant + Discord).
- 🌐 **Podpora více webhooků současně**:
  - **Home Assistant Webhook** (pro notifikace na mobil a integraci do chytré domácnosti)
  - **Discord Webhook** (barevný embed s jednotlivými hodinami a předměty)
  - **Telegram Bot** (přímá zpráva přes Telegram bota)
  - **ntfy.sh** (bezplatné mobilní push notifikace na Android / iOS bez nutnosti vlastního serveru)
  - **Slack**
  - **Obecný Generic HTTP JSON Webhook**
- 🐳 **Optimalizováno pro Portainer & Auto-Update**.

---

## 🛠️ Nasazení v Portaineru (s Auto-Update)

Portainer umožňuje nasadit stack přímo z Git repozitáře a automaticky jej aktualizovat při každém commitu do větve `main`.

### Postup krok za krokem:

1. Otevřete **Portainer** -> **Stacks** -> **Add stack**.
2. Zvolte metodu **Repository**.
3. Vyplňte:
   - **Name:** `jecna-rozvrh-notifier`
   - **Repository URL:** `https://github.com/<vas-github-ucet>/jecna-rozvrh-notifier`
   - **Repository reference:** `refs/heads/main`
   - **Compose path:** `docker-compose.yml`
   - **Authentication:** Zadejte vaše GitHub jméno a Personal Access Token (PAT).
4. Zapněte **Automatic updates**:
   - Můžete vybrat **Polling** (např. každých 5 minut Portainer zkontroluje nové commity)
   - Nebo **Webhook** (Portainer vygeneruje URL, které zavolá GitHub Actions na push).
5. V sekci **Environment variables** nastavte proměnné (viz tabulka níže):
   - `CLASS_NAME`: `C4b`
   - `CHECK_INTERVAL_SECONDS`: `900`
   - `HOMEASSISTANT_WEBHOOK_URL`: `http://<HA_IP>:8123/api/webhook/jecna_supl_webhook`
   - (volitelně) `DISCORD_WEBHOOK_URL`, `NTFY_URL`, atd.
6. Klikněte na **Deploy the stack**.

---

## 💻 Spuštění přes Docker Compose (CLI)

```bash
# 1. Klonování
git clone https://github.com/<vas-github-ucet>/jecna-rozvrh-notifier.git
cd jecna-rozvrh-notifier

# 2. Vytvoření konfigurace
cp .env.example .env
nano .env   # Upravte přihlašovací údaje a webhook URL

# 3. Spuštění kontejneru na pozadí
docker compose up -d --build
```

Logy můžete sledovat příkazem:
```bash
docker logs -f jecna-rozvrh-notifier
```

---

## 📱 Konfigurace Webhooků

### 1. Home Assistant Webhook

Přidejte následující automatizaci do vašeho `automations.yaml` v Home Assistant (nebo vytvořte novou automatizaci přes UI -> Spouštěč: Webhook):

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
  - action: notify.notify   # nebo např. notify.mobile_app_vas_telefon
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

### 2. Discord Webhook

1. Na Discord serveru otevřete **Nastavení kanálu** -> **Integrace** -> **Webhooky** -> **Vytvořit webhook**.
2. Zkopírujte URL webhooku a vložte do `.env`:
   ```env
   DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/123456789/abcdef...
   ```
Při změně pošle přehledný vložený embed s ikonou Ječné a rozpisem hodin.

---

### 3. ntfy.sh (Bleskové push notifikace na mobil)

Pokud chcete okamžité push notifikace na mobilní telefon bez konfigurace Home Assistant:
1. Stáhněte si aplikaci **ntfy** z Google Play nebo App Store.
2. V aplikaci klikněte na `+` a zadejte libovolné unikátní téma, např. `jecna_supl_notifikace`.
3. V `.env` nastavte:
   ```env
   NTFY_URL=https://ntfy.sh/jecna_supl_notifikace
   ```

---

### 4. Telegram Bot

1. Vytvořte bota přes `@BotFather` a získejte `BOT_TOKEN`.
2. Zjistěte své `CHAT_ID` (např. přes `@userinfobot`).
3. V `.env` nastavte:
   ```env
   TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
   TELEGRAM_CHAT_ID=987654321
   ```

---

## ⚙️ Seznam proměnných prostředí

| Proměnná | Výchozí hodnota | Popis |
|---|---|---|
| `CHECK_INTERVAL_SECONDS` | `900` (15 minut) | Frekvence kontroly rozvrhu v sekundách |
| `CLASS_NAME` | `C4b` | Sledovaná třída studenta (např. `C4b`, `A2a`) |
| `ALERT_ON_STARTUP` | `false` | Zda poslat notifikace na již existující změny při prvním spuštění |
| `REPEAT_ALL_CHANGES` | `true` | Při nalezení změny poslat kompletní přehled všech platných suplování |
| `MORNING_NOTIFICATION_ENABLED` | `true` | Zda posílat ranní souhrnnou notifikaci |
| `MORNING_NOTIFICATION_TIME` | `07:00` | Čas ranní notifikace ve formátu `HH:MM` |
| `MORNING_NOTIFICATION_TARGETS` | `all` | Cílové služby pro ranní notifikaci (`all`, `haos`, `discord`, `haos,discord`, atd.) |
| `MORNING_NOTIFICATION_ONLY_IF_CHANGES` | `true` | Poslat ranní notifikaci pouze, pokud jsou pro daný den změny |
| `SUBSTITUTION_API_URL` | `https://jecnarozvrh.jzitnik.dev/versioned/v3` | Zdrojový endpoint mimořádného rozvrhu |
| `STATE_FILE_PATH` | `/data/state.json` | Cesta k souboru s historií změn |
| `HOMEASSISTANT_WEBHOOK_URL` | `""` | URL Home Assistant webhooku |
| `DISCORD_WEBHOOK_URL` | `""` | URL Discord webhooku |
| `TELEGRAM_BOT_TOKEN` | `""` | Token Telegram bota |
| `TELEGRAM_CHAT_ID` | `""` | ID chatu pro Telegram bota |
| `NTFY_URL` | `""` | URL tématického kanálu ntfy.sh |
| `SLACK_WEBHOOK_URL` | `""` | URL Slack webhooku |
| `GENERIC_WEBHOOK_URL` | `""` | URL obecného JSON webhooku |

---

## 📂 Struktura projektu

```
jecna-rozvrh-notifier/
├── .github/
│   └── workflows/
│       └── docker-publish.yml # Automatický build GHCR image na push
├── main.py                    # Hlavní smyčka a zpracování stavu
├── jecna.py                   # Dotazování na Ječná API a výpočet diffů
├── webhooks.py                # Odesílání na HA, Discord, Telegram, ntfy, atd.
├── Dockerfile                 # Alpine Python kontejner
├── docker-compose.yml         # Konfigurace pro Portainer a Compose
├── requirements.txt           # Závislosti
├── .env.example               # Šablona nastavení
└── README.md                  # Dokumentace
```

---

## 👏 Poděkování & Kredity / Credits

Tento projekt staví na skvělé práci komunity okolo SPŠE Ječná:

- **[Tomáš Hůla (@tomhula)](https://github.com/tomhula)** – za vytvoření open-source Android aplikace [JecnaMobile](https://github.com/tomhula/JecnaMobile), která posloužila jako prvotní inspirace a zdroj logiky parseru rozvrhu.
- **[Jaroslav Žitník (@jzitnik)](https://github.com/jzitnik)** – za vytvoření a provoz spolehlivého API pro rozvrh a suplování [jecnarozvrh.jzitnik.dev](https://jecnarozvrh.jzitnik.dev/), které tento kontejner využívá pro získávání dat.

---

## 📄 Licence

Tento projekt je open-source pod licencí MIT.
