# ktv-hermes

An [MCP](https://modelcontextprotocol.io) server for the TUL KTV sports-centre reservation
system, **rezervace.ktv.tul.cz** (Akademické sportovní centrum). It lets an AI agent
(Hermes, Claude Desktop, Cursor, …) find, book and cancel **gym** and **sauna** blocks with your
own KTV account, and compute fun statistics from your reservation history.

Unofficial; it drives the same web pages you use in the browser. Payment still happens on site.

## Tools

| Tool | What it does |
|---|---|
| `find_gym_slots(date_from?, date_to?, only_available?)` | Future `ASC POSILOVNA` blocks with occupancy (default: next 7 days) |
| `find_sauna_slots(date_from?, date_to?, only_available?, gender?)` | Future sauna blocks, filtered to the ones your gender may book |
| `upcoming_reservations(weeks_ahead?)` | Your booked activities that haven't ended yet |
| `reservation_history(since?)` | Your past reservations (default: last 365 days) |
| `reservation_stats(since?)` | Totals, hours, weekday/time/month breakdowns, longest weekly streak |
| `book_gym(activity_id)` | Book a gym block |
| `book_sauna(activity_id, gender?)` | Book a sauna block (refuses blocks not allowed for your gender) |
| `cancel_reservation(activity_id)` | Cancel a gym or sauna reservation |

Every booking and cancellation returns a `calendar` object (`summary`, `start`, `end`,
`location`, `uid`, ready-made `ics`). The server never touches your calendar itself: the host
agent creates the event after booking and deletes it after cancelling (the event description
contains `ktv-activity-id: N` so it can be found again).

### Sauna rules

Sauna blocks are titled `Sauna MUŽI`, `Sauna ŽENY` or `Sauna SPOLEČNÁ` (sometimes with a gender
suffix such as `Sauna SPOLEČNÁ (MUŽI)`) and listed in two changing-room rows
(`SAUNA mužská šatna`, `SAUNA ženská šatna`). The server is deliberately conservative and only
books a block when **both** hold:

- the block title names your gender (MUŽI for `male`, ŽENY for `female`), and
- the row is your own changing room.

Plain mixed blocks and unknown block types or rooms are refused rather than guessed.

## Setup

Requires Python ≥ 3.10.

```bash
git clone https://github.com/tomyjany/hermes-tul-ktv.git
cd hermes-tul-ktv
uv venv && uv pip install -e .      # or: python -m venv .venv && .venv/bin/pip install -e .
cp .env.example .env                # fill in your credentials (never commit .env)
```

Configuration (environment variables or `.env` in the working directory):

| Variable | Meaning |
|---|---|
| `KTV_USERNAME` | Your rezervace.ktv.tul.cz login e-mail |
| `KTV_PASSWORD` | Your password |
| `KTV_GENDER` | `male` or `female`; default for sauna filtering/booking |

History weeks that are fully in the past are cached in `~/.cache/ktv-hermes/` (readable only by you),
so `reservation_stats` is slow only the first time.

> The KTV server sends an incomplete TLS chain. The package bundles the missing public
> intermediate certificate (`GEANT TLS RSA 1`) and adds it to certifi's roots; TLS verification
> stays on.

## Use with an MCP host

### Hermes Agent (`~/.hermes/config.yaml`)

Hermes starts stdio servers with a filtered environment, so pass the variables explicitly;
`${VAR}` is resolved from `~/.hermes/.env`:

```yaml
mcp_servers:
  ktv:
    command: /path/to/hermes-tul-ktv/.venv/bin/ktv-hermes
    env:
      KTV_USERNAME: ${KTV_USERNAME}
      KTV_PASSWORD: ${KTV_PASSWORD}
      KTV_GENDER: male
```

### Claude Desktop / other hosts

```json
{
  "mcpServers": {
    "ktv": {
      "command": "/path/to/hermes-tul-ktv/.venv/bin/ktv-hermes",
      "env": { "KTV_USERNAME": "…", "KTV_PASSWORD": "…", "KTV_GENDER": "male" }
    }
  }
}
```

## Development

```bash
uv pip install -e '.[dev]'
pytest
```

Tests run offline against synthetic HTML fixtures; they never log in or book anything.

## License

MIT
