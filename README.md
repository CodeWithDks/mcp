# 🔌 MCP — Model Context Protocol Servers

A growing collection of **Model Context Protocol (MCP) servers**, each built to explore a different real-world use case — from simple utilities to database-connected agents and DevOps automation. Every module lives in its own numbered folder and is a complete, runnable MCP server on its own.

This repo is where I learn MCP by building it: one server at a time, each one a little more advanced than the last.

---

## 🧠 What is MCP?

The [Model Context Protocol](https://modelcontextprotocol.io/) is an open standard that lets AI applications (like Claude, Cursor, or any MCP-compatible client) connect to external tools, data, and systems in a consistent way — through **Tools** (actions the AI can perform), **Resources** (data the AI can read), and **Prompts** (reusable instructions).

---

## 📂 Repository Structure

```
mcp/
├── 01_simple_math/          ✅ Calculator MCP server (FastMCP)
├── 02_expense_tracker/      🚧 Planned
├── 03_devops_mcp/           🚧 Planned
├── pyproject.toml
├── pyrightconfig.json
├── uv.lock
└── .gitignore
```

Each module is self-contained with its own `README.md` explaining what it does and how to run it. New modules will be added as `04_...`, `05_...`, and so on — this repo will keep growing as I explore new kinds of MCP servers.

---

## 📖 Modules

### ✅ `01_simple_math` — Calculator MCP Server
A calculator MCP server built with [FastMCP](https://gofastmcp.com/), demonstrating all three core MCP primitives:

| Primitive | Examples |
|---|---|
| **Tools** | `add`, `subtract`, `multiply`, `divide`, `percentage` |
| **Resources** | `calculator://about`, `calculator://operations`, `calculator://examples` |
| **Prompts** | `solve_math_problem`, `explain_calculation`, `check_calculation` |

📄 [Read the module README](./01_simple_math/README.md)

### 🚧 `02_expense_tracker` — Planned
An MCP server for tracking and querying expenses, backed by a database.

### 🚧 `03_devops_mcp` — Planned
An MCP server exposing DevOps-related tools and automation.

> As each module is built, its status above will move from 🚧 Planned to ✅ Done, with its own README linked here.

---

## 🛠 Tech Stack

- **Python** (3.12+)
- **[FastMCP](https://gofastmcp.com/)** — the MCP server framework used across modules
- **[MCP SDK](https://github.com/modelcontextprotocol/python-sdk)** (`mcp[cli]`)
- **httpx** — for MCP servers that call external APIs
- **psycopg** — for MCP servers backed by PostgreSQL
- **Pydantic / pydantic-settings** — data validation & config management
- **[uv](https://docs.astral.sh/uv/)** — dependency management (`uv.lock`)

---

## ⚙️ Getting Started

Clone the repository:

```bash
git clone https://github.com/CodeWithDks/mcp.git
cd mcp
```

This project uses [`uv`](https://docs.astral.sh/uv/) for dependency management:

```bash
uv sync
```

Or with plain `pip`:

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .
```

Then head into any module folder and follow its own README to run that specific server, e.g.:

```bash
cd 01_simple_math
python calculator_mcp.py
```

---

## 🔐 Environment Variables

Some modules (e.g. anything using `psycopg`) will need credentials such as a database connection string. Each module that requires configuration will document its own `.env` variables in its README.

> ⚠️ Never commit real credentials. Use a local `.env` file (already excluded via `.gitignore`) and reference values with `os.getenv(...)` / `pydantic-settings`.

---

## 🎯 Roadmap

- [x] Simple math / calculator MCP server
- [ ] Expense tracker MCP server (database-backed)
- [ ] DevOps MCP server
- [ ] MCP server with external API integration (`httpx`-based)
- [ ] MCP client examples showing how to connect to these servers

---

## 📌 Purpose

This repository exists to:

- Learn the Model Context Protocol by building real, working servers
- Explore different categories of MCP servers — utilities, database-backed tools, DevOps automation, and more
- Keep a reusable reference of MCP server patterns for future projects

---

## 📄 License

Open source — feel free to explore, learn from, or build on any module here.

---

## 👨‍💻 Author

Built by [Deepak Kumar Singh](https://github.com/CodeWithDks) as a hands-on learning project for the Model Context Protocol.

If you find this useful, consider giving the repo a ⭐.