# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Single-file Streamlit app (`teste5.py`) that simulates military promotion careers over time for a Brazilian military police force. It projects promotions, vacancy absorption, and retirements across promotion cycles up to a target date, and can track individual personnel by registration number (`Matricula`). Code, UI, and domain terms are in Brazilian Portuguese.

## Commands

```bash
pip install -r requirements.txt   # install deps (streamlit, pandas, openpyxl, xlsxwriter, python-dateutil, altair)
streamlit run teste5.py           # run the app (opens in browser)
```

There is no test suite, linter, or build step configured.

## Data model

Three Excel files in the repo root are the data source — one per career track (*quadro*). The app reads them at startup from the current working directory, so run it from the repo root.

| File | Quadro |
|------|--------|
| `militares.xlsx` | QOA/QPC (Administrativo) — the main track |
| `condutores.xlsx` | QOMT/QPMT (Condutores / drivers) |
| `musicos.xlsx` | QOM/QPM (Músicos / musicians) |

Each row is one service member. Columns (see `carregar_dados`):
- `Matricula` (int) — registration number, the per-person key.
- `Pos_Hierarquica` (int) — ordering within a rank; lower = more senior. Promotions process candidates in this order.
- `Posto_Graduacao` (str) — current rank; must be one of `HIERARQUIA`.
- `Data_Admissao`, `Data_Nascimento`, `Ultima_promocao` (dates, `dayfirst=True` / dd/mm/yyyy).
- `Excedente` (str) — `"x"` marks a member promoted *over* the legal vacancy limit (surplus); empty means occupying a real slot. Auto-created/filled if missing.

The `.pdf` files in the root are the governing laws (Lei 8.668/2022, Lei 9.392/2024) — reference material that defines the vacancy tables and promotion rules, not used at runtime.

## Architecture

The whole simulation lives in `executar_simulacao_quadro(...)`. Understanding it requires reading these pieces together:

**Promotion cycles.** Promotions happen twice a year on fixed dates: **June 26** and **November 29** (`datas_ciclo`). The simulation steps through every such date from today up to the target date, applying these phases in order each cycle:

1. **(Optional) Gerador Quântico** — see below.
2. **Promoções (A)** — walk up `HIERARQUIA` rank by rank. A member is promoted when years-in-rank ≥ `TEMPO_MINIMO` *and* a vacancy is open. Ranks in `POSTOS_COM_EXCEDENTE` additionally allow promotion *over* the limit once years-in-rank ≥ 6, marking the member `Excedente = "x"` (surplus, not counted against the limit). Leftover open vacancies per rank are recorded as `sobras`.
3. **Absorção (B)** — surplus (`"x"`) members are converted to real slot-holders when real vacancies free up, in `Pos_Hierarquica` order.
4. **Aposentadoria (C)** — members retire at age ≥ 63 or service ≥ `tempo_aposentadoria` (slider, 30–35), moving from the active `df` to `df_inativos`.

**Vacancy tables.** `VAGAS_QOA`, `VAGAS_QOMT`, `VAGAS_QOM` are the legal slot counts per rank for each quadro. `CEL` uses `9999` as effectively unlimited.

**Vacancy migration (QOA only).** When simulating QOA, the condutores and músicos quadros are simulated first; their unfilled vacancies (`sobras`) per cycle are passed into the QOA run as `vagas_extras_dict` and added on top of `VAGAS_QOA`. Note the músicos→QOA mapping halves (`ceil(q/2)`) the migrated count for officer ranks above `SUB TEN` (see `main`).

**Gerador Quântico.** A toggle that randomly retires a percentage (15–30%) of each admission cohort (`Data_Admissao` group) when it reaches 32, 33, or 34 years of service. `turmas_processadas_quantico` guards against cutting the same cohort twice for the same service-year.

**Outputs.** Returns `(df_final, df_inativos, historicos, sobras_por_ciclo)`. `historicos` is a per-`Matricula` event log (only for the up-to-5 members the user selected to follow) rendered as tabs in the UI. Active and inactive rosters are offered as Excel downloads.

The Streamlit UI (`main`) wires the sidebar controls (quadro selector, tracked matrículas, target date, retirement years, quantum toggle) to the engine and renders results. All simulation logic is pure-pandas and UI-independent except for `st.error`/`st.spinner` calls.

## Conventions

- Rank order, minimum time-in-rank, surplus-eligible ranks, and vacancy counts are hardcoded constants at the top of `teste5.py`. Changing promotion rules means editing `HIERARQUIA`, `TEMPO_MINIMO`, `POSTOS_COM_EXCEDENTE`, and the `VAGAS_*` dicts there.
- Dates are parsed and compared as pandas `Timestamp` with `dayfirst=True`; year differences use `dateutil.relativedelta(...).years` (whole years).
