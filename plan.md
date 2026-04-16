# Plan: BigQuery-basert ATB bussdata-analyse

## Bakgrunn

Enturs sanntids-API (`/realtime/v1/rest/et`) returnerer kun navarende tilstand - ingen historikk.
Historisk data finnes i **Google BigQuery**, gratis tilgjengelig via `data.entur.no`.
Robin Kaveland (kaaveland/bus-eta) brukte nettopp dette for a bygge sin analyse med data tilbake til 2020.

Malet er et Python-prosjekt som kjorer i Docker, spor direkte mot BigQuery, og senere kan bli en MCP-server.

## Tilgang til BigQuery

### Hva som trengs

1. **Google-konto** (vanlig Gmail eller Google Workspace)
2. **Google Cloud-prosjekt** - gratis a opprette pa console.cloud.google.com
3. **BigQuery API aktivert** i prosjektet (er det som standard)
4. **Service Account** med nokkelfil (JSON) for autentisering fra Docker

### Steg for steg

1. Ga til [console.cloud.google.com](https://console.cloud.google.com)
2. Opprett et nytt prosjekt (f.eks. `atb-analyse`)
3. BigQuery har **1 TB gratis sporringer per manad** (on-demand pricing)
4. Opprett en Service Account:
   - IAM & Admin > Service Accounts > Create
   - Gi rollen "BigQuery Job User" (for a kjore sporringer)
   - Opprett en JSON-nokkel og last den ned
5. Legg nokkelfilen i prosjektet (f.eks. `credentials/sa-key.json`, gitignored)
6. Sett miljovariabel `GOOGLE_APPLICATION_CREDENTIALS=/app/credentials/sa-key.json` i Docker

**Viktig**: Dataen i `ent-data-sharing-ext-prd` er offentlig delt. Du trenger ikke tilgang til Enturs prosjekt - du trenger kun et *eget* GCP-prosjekt for a kjore sporringene (BigQuery krever et prosjekt for fakturering av sporrekostnader).

### Alternativ: brukerautentisering

For lokal utvikling kan du bruke `gcloud auth application-default login` i stedet for service account. Da brukes din personlige Google-konto. Men dette fungerer darlig i Docker, sa service account anbefales.

## Datamodell i BigQuery

### Prosjekt og datasett

- **GCP-prosjekt**: `ent-data-sharing-ext-prd`
- **Datasett**: `realtime_siri_et`

### Tabell: `realtime_siri_et_last_recorded`

Hovedtabellen. En rad per stoppbesok med siste registrerte faktiske tider. **2,8 milliarder rader, 639 GB**. Data fra Q1 2020, oppdateres hver morgen.

| Kolonne | Type | Beskrivelse |
|---------|------|-------------|
| recordedAtTime | TIMESTAMP | Tidspunkt da dataobjektet ble opprettet/publisert |
| lineRef | STRING | Linjereferanse, f.eks. `ATB:Line:2_1` |
| directionRef | STRING | Retning, f.eks. `2` (Outbound) |
| operatingDate | DATE | Driftsdato, f.eks. `2020-01-10` |
| dayOfTheWeek | INTEGER | Ukedag, f.eks. `3` (onsdag) |
| serviceJourneyId | STRING | Tur-ID, f.eks. `RUT:ServiceJourney:17-154797-20890925` |
| datedServiceJourneyId | STRING | Tur-ID med dato |
| operatorRef | STRING | Operator, f.eks. `nettbuss` |
| vehicleMode | STRING | Transporttype, f.eks. `bus` |
| extraJourney | BOOLEAN | Om turen er en ekstraavgang |
| journeyCancellation | BOOLEAN | Om turen er innstilt |
| stopPointRef | STRING | Stoppested i NSR-format, f.eks. `NSR:Quay:105273` |
| sequenceNr | INTEGER | Rekkefolge i stoppsekvensen |
| stopPointName | STRING | Navn pa stoppested, f.eks. `Storgata` |
| originName | STRING | Forste stopp pa turen |
| destinationName | STRING | Siste stopp pa turen |
| extraCall | BOOLEAN | Om stoppet er i tillegg til planlagt sekvens |
| stopCancellation | BOOLEAN | Om stoppet er innstilt |
| estimated | BOOLEAN | Om dataen er estimert (ikke faktisk) |
| aimedArrivalTime | TIMESTAMP | Planlagt ankomsttid |
| arrivalTime | TIMESTAMP | Faktisk ankomsttid |
| aimedDepartureTime | TIMESTAMP | Planlagt avgangstid |
| departureTime | TIMESTAMP | Faktisk avgangstid |
| dataSource | STRING | Datakilde-kode, f.eks. `ATB` |
| dataSourceName | STRING | Datakilde-navn, f.eks. `AtB` |

### Tabell: `realtime_siri_et_estimated_times`

Estimerte tider tatt pa ulike tidspunkter for ankomst/avgang. Brukes for a analysere presisjon i sanntidsestimater.

| Kolonne | Type | Beskrivelse |
|---------|------|-------------|
| operatingDate | DATE | Driftsdato |
| dataSource | STRING | Datakilde-kode |
| transportMode | STRING | Transportmodus, f.eks. `BUS` |
| lineRef | STRING | Linjereferanse |
| serviceJourneyId | STRING | Tur-ID |
| datedServiceJourneyId | STRING | Tur-ID med dato |
| stopPointRef | STRING | Stoppested (NSR) |
| parentStopPointRef | STRING | Overordnet stoppested |
| stopPointName | STRING | Stoppestedsnavn |
| sequenceNr | INTEGER | Rekkefolge |
| timeDeltaMinutes | INTEGER | Minutter for faktisk ankomst/avgang estimatet er tatt |
| AimedArrivalTime | TIMESTAMP | Planlagt ankomsttid |
| arrivalTime | TIMESTAMP | Faktisk ankomsttid |
| estimatedArrivalTime | TIMESTAMP | Estimert ankomsttid pa det tidspunktet |
| EstimatedArrivalRecordedAtTime | TIMESTAMP | Nar estimatet ble generert |
| AimedDepartureTime | TIMESTAMP | Planlagt avgangstid |
| departureTime | TIMESTAMP | Faktisk avgangstid |
| estimatedDepartureTime | TIMESTAMP | Estimert avgangstid pa det tidspunktet |
| EstimatedDepartureRecordedAtTime | TIMESTAMP | Nar estimatet ble generert |

### Relaterte tabeller (national_stop_registry)

Robin bruker ogsa disse for a berike med koordinater og stoppested-metadata:

- `national_stop_registry.quays_last_version` - Plattformer/quays med koordinater
- `national_stop_registry.stop_places_last_version` - Stoppesteder med navn, sone, transportmodus

## Python-biblioteker

```
google-cloud-bigquery    # BigQuery-klient
pyarrow                  # Effektiv dataoverfor fra BigQuery (Arrow-format)
db-dtypes                # BigQuery-spesifikke datatyper for pandas/arrow
```

Robins kode bruker `google.cloud.bigquery.Client` med parameteriserte sporringer:

```python
from google.cloud import bigquery

client = bigquery.Client(project="mitt-gcp-prosjekt")

# Parameterisert spørring - trygt mot injection
job_config = bigquery.QueryJobConfig(
    query_parameters=[
        bigquery.ScalarQueryParameter("operating_date", "DATE", date(2024, 6, 15))
    ]
)
result = client.query("""
    SELECT lineRef, stopPointName, arrivalTime, departureTime, aimedArrivalTime
    FROM `ent-data-sharing-ext-prd.realtime_siri_et.realtime_siri_et_last_recorded`
    WHERE operatingDate = @operating_date AND dataSource = 'ATB'
    LIMIT 100
""", job_config=job_config)

for row in result:
    print(row)
```

## Docker-oppsett

```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app
COPY pyproject.toml .
RUN uv sync --no-dev
COPY *.py src/
ENTRYPOINT ["uv", "run", "python", "-m", "src"]
```

```yaml
# docker-compose.yml
services:
  query:
    build: ./query
    volumes:
      - ./credentials:/app/credentials:ro
    environment:
      - GOOGLE_APPLICATION_CREDENTIALS=/app/credentials/sa-key.json
      - GCP_PROJECT=mitt-gcp-prosjekt
```

Credentials-mappen med nokkelfilen mountes som read-only volume. Nokkelfilen skal aldri inn i git.

## Kostnader

- **BigQuery on-demand**: 1 TB gratis sporringer per manad
- Tabellen er 639 GB. En full tabellscan bruker hele gratiskvoten
- **Viktig**: Filtrer ALLTID pa `operatingDate` - tabellen er partisjonert pa denne kolonnen, sa sporringer med dato-filter leser kun relevante partisjoner
- En sporring for en enkelt dag (~8M rader) koster ca 1-2 GB av kvoten
- Med ATB-filter i tillegg: enda mindre

## Eksempelspørringer for ATB

```sql
-- Forsinkelse per linje for en gitt dag
SELECT lineRef, AVG(TIMESTAMP_DIFF(departureTime, aimedDepartureTime, SECOND)) as avg_delay_s
FROM `ent-data-sharing-ext-prd.realtime_siri_et.realtime_siri_et_last_recorded`
WHERE operatingDate = '2025-01-15' AND dataSource = 'ATB' AND departureTime IS NOT NULL
GROUP BY lineRef ORDER BY avg_delay_s DESC

-- Alle stopp for linje 3 pa en bestemt tur
SELECT sequenceNr, stopPointName, aimedDepartureTime, departureTime,
       TIMESTAMP_DIFF(departureTime, aimedDepartureTime, SECOND) as delay_s
FROM `ent-data-sharing-ext-prd.realtime_siri_et.realtime_siri_et_last_recorded`
WHERE operatingDate = '2025-01-15' AND lineRef = 'ATB:Line:2_3'
ORDER BY serviceJourneyId, sequenceNr

-- Antall turer per dag siste manad
SELECT operatingDate, COUNT(DISTINCT serviceJourneyId) as turer
FROM `ent-data-sharing-ext-prd.realtime_siri_et.realtime_siri_et_last_recorded`
WHERE operatingDate BETWEEN '2025-01-01' AND '2025-01-31' AND dataSource = 'ATB'
GROUP BY operatingDate ORDER BY operatingDate
```

Enturs egne eksempelspørringer finnes her:
https://colab.research.google.com/drive/1UqMTS1JQhN7z07iX57X2Epg3x3ugx4x7

## Videre: MCP-server

Neste steg er a pakke dette som en MCP-server som eksponerer sporringer som tools.
MCP-serveren kan:
- Ta imot naturlig sprak og oversette til BigQuery SQL
- Eksponere ferdige sporringer (forsinkelse per linje, sammenligning mellom perioder, etc.)
- Returnere resultater i strukturert format

MCP-serveren kjorer ogsa i Docker, og er da tilgjengelig som en ekstern MCP-server for Claude Code eller andre klienter.

## Referanser

- BigQuery-tabellen: https://data.entur.no/public/datasets/realtime_siri_et
- Enturs eksempelspørringer: https://colab.research.google.com/drive/1UqMTS1JQhN7z07iX57X2Epg3x3ugx4x7
- Robins bloggpost: https://kaveland.no/posts/2025-05-28-turning-the-bus-sql/
- Robins kode: https://github.com/kaaveland/bus-eta
- Kontakt Entur data-team: team.dataanalyse@entur.org
