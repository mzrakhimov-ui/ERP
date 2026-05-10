# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**A Tex Sanoat** — a Telegram ERP bot for a textile factory. It manages the workflow between three shop-floor roles: cutters (bichuvchi), distributors (razdacha), and sewers (chevar), with an admin role for oversight. The entire application is a single Python file (`Bot.py`).

## Running the Bot

```bash
# Install dependencies (note: file is named "Requirements", not requirements.txt)
pip install -r Requirements

# Copy and configure environment
cp .env.example .env
# Set BOT_TOKEN in .env

# Run
python Bot.py
```

There is no test suite and no linter configured. The bot connects to `fabrika.db` (SQLite, auto-created on first run) and creates a `backups/` directory automatically.

## Architecture

### Single-file structure
All logic lives in `Bot.py`. Sections are delimited by comments like `# ================= BICHUV BO'LIMI =================`.

### FSM (Finite State Machine) driven UI
aiogram 3.x FSM is used for every multi-step interaction. State groups defined at the top:
- `LoginState` — authentication (id → password)
- `BichuvState` — cutter enters new cut batch
- `RazdachaState` — distributor assigns work to a sewer
- `ChevarState` — sewer submits completed work
- `NarxState` — admin sets per-model pricing
- `AdminClearState` — admin clears the database (guarded by hardcoded password `Mz12345`)

### Authentication model
Users authenticate by entering their numeric employee ID then password. On success, `chat_id` (Telegram user ID) is stored in the `hodimlar` table row. Role is looked up from `hodimlar.rol` on every protected handler. Logout clears `chat_id` to NULL.

### Role-based menus
`get_main_menu(rol, user_id)` returns a `ReplyKeyboardMarkup` tailored to the user's role. All business logic handlers check `hodimlar.rol` directly from the DB — there is no session/middleware layer storing role in memory.

### Database schema (SQLite — `fabrika.db`)

| Table | Purpose |
|---|---|
| `hodimlar` | Employees: id, parol, ism, rol, chat_id, sana |
| `bichuv_ombor` | Cut inventory: model, kod, razmer, soni, status (0=new, 1=sent to razdacha) |
| `razdacha_ombor` | Distributor inventory: model, kod, razmer, soni |
| `ishlar` | Active work orders: model, kod, razmer, umumiy_soni, qolgan_soni, topshirildi_soni, chevar_id, status, vaqt |
| `bitgan_ishlar` | Completed work history: used to calculate chevar balances |
| `tariflar` | Price per cut code: bichuv_id (kod), narx (so'm) |

### Work order lifecycle (`ishlar.status`)
```
kutilmoqda  →  tikilmoqda  →  topshirildi_kutilmoqda  →  yakunlandi
(assigned)     (accepted)     (chevar submitted)          (razdacha confirmed)
```

### Chevar balance calculation
`bitgan_ishlar` JOIN `tariflar` ON `kodi = bichuv_id`, grouped by `kodi`, multiplied by `narx`. Sewers with no tariff assigned show 0 so'm.

## Known Code Issues

- `📦 Ombor holati` handler and `admin_stats` are each registered **twice** (lines ~790 and ~816/884). The second definitions shadow the first. The second `raz_ombor_status` at line 869 is a bare `async def` with no `@dp.message` decorator — it is dead code.
- Line 890 uses `JSON_EXTRACT(bichuv_ombor, '$')` which is invalid SQLite syntax. The commented-out line below it (`SELECT SUM(soni) FROM bichuv_ombor WHERE status=0`) is the correct query.
- `MemoryStorage` is used for FSM — all in-flight states are lost on bot restart.

## Environment

- **Python:** 3.9+
- **Framework:** aiogram 3.7.0 (async, decorator-based handlers, `@dp.message`, `@dp.callback_query`)
- **DB:** SQLite 3 via stdlib `sqlite3` (synchronous calls inside async handlers)
- **Config:** `python-dotenv` reads `BOT_TOKEN` from `.env`
