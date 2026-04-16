# ATB MCP Server

MCP-server for analyse av ATB-bussdata fra Trondheim via Google BigQuery.

Bruker Enturs offentlige BigQuery-datasett med sanntids SIRI ET-data (fra Q1 2020).

## Forutsetninger

- [Docker](https://docs.docker.com/get-docker/) med Docker Compose
- En [Google Cloud](https://console.cloud.google.com)-konto med et GCP-prosjekt

## GCP-oppsett (første gang)

Du trenger et eget GCP-prosjekt for fakturering av spørringer. Datasettet hos Entur er offentlig — du trenger ikke tilgang til Enturs prosjekt.

1. Gå til [console.cloud.google.com](https://console.cloud.google.com) og logg inn med Google-kontoen din
2. Opprett et nytt prosjekt (f.eks. `atb-analyse`) via «Select a project» → «New Project»
3. BigQuery API er aktivert som standard i nye prosjekter
4. Opprett en Service Account:
   - Gå til **IAM & Admin → Service Accounts → Create Service Account**
   - Gi den et navn, f.eks. `atb-mcp`
   - Tildel rollen **BigQuery Job User** (nok til å kjøre spørringer)
   - Klikk ferdig — du trenger ikke gi brukertilgang til service accounten
5. Opprett en JSON-nøkkel:
   - Klikk på service accounten du nettopp opprettet
   - Gå til fanen **Keys → Add Key → Create new key → JSON**
   - Last ned filen og lagre den som `credentials/sa-key.json` i dette prosjektet

> **Merk**: `credentials/` er gitignored. Nøkkelfilen skal aldri committes.

## Oppsett

1. Legg service account-nøkkelen i `credentials/sa-key.json` (se over)
2. Kopier og tilpass miljøvariabler:

```bash
cp .env.example .env
# Sett GCP_PROJECT til prosjekt-IDen du opprettet
```

## Kjøring

```bash
docker compose up --build
```

Serveren starter på port 8000 (HTTP-transport).

## Koble til Claude Desktop

Claude Desktop støtter ikke HTTP-transport direkte. Bruk `mcp-remote` (via `npx`) som bro mellom Claude Desktop og den HTTP-baserte serveren. Du trenger [Node.js](https://nodejs.org/) installert.

Start serveren med Docker (se over), og legg så til følgende i Claude Desktops konfigurasjonsfil:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "atb": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:8000/mcp"]
    }
  }
}
```

Start Claude Desktop på nytt etter at du har lagret filen. Du skal da se ATB-verktøyene tilgjengelig i samtaler.

## MCP-verktøy

| Verktøy | Beskrivelse |
|---------|-------------|
| `get_schema` | Vis kolonner og typer for en tabell |
| `query` | Kjør vilkårlig BigQuery SQL |
| `dry_run` | Estimer datamengde uten å kjøre spørringen |
| `list_lines` | List alle ATB-linjer for en gitt dato |
| `delay_summary` | Forsinkelsesstatistikk per linje eller per stopp |
| `nearby_stops` | Finn holdeplasser nær en posisjon |

## Miljøvariabler

| Variabel | Standard | Beskrivelse |
|----------|----------|-------------|
| `GOOGLE_APPLICATION_CREDENTIALS` | - | Sti til service account JSON-nøkkel |
| `GCP_PROJECT` | `atb-analyse` | GCP-prosjekt for fakturering |
| `BQ_MAX_BYTES_GB` | `10` | Maks GB per spørring |
| `MCP_TRANSPORT` | `http` | Transport (`http` eller `stdio`) |
| `MCP_HOST` | `0.0.0.0` | Host å lytte på |
| `MCP_PORT` | `8000` | Port å lytte på |

## Kostnader

BigQuery har 1 TB gratis spørringer per måned. En dag med ATB-data er ca 1-2 GB. Filtrer alltid på `operatingDate` (partisjonsnøkkel) og `dataSource = 'ATB'`.

## Referanser

- [BigQuery-datasettet](https://data.entur.no/public/datasets/realtime_siri_et)
- [Enturs eksempelspørringer](https://colab.research.google.com/drive/1UqMTS1JQhN7z07iX57X2Epg3x3ugx4x7)
