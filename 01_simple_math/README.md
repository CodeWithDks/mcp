# Calculations 🧮 MCP Server

A simple and extensible **Model Context Protocol (MCP) server** built with [FastMCP](https://gofastmcp.com/).

This server provides mathematical **Tools**, **Resources**, and **Prompts** that can be used by MCP-compatible AI clients.

## ✨ Features

### 🛠️ Tools

Tools allow an AI client to perform calculations.

| Tool         | Description                                      |
| ------------ | ------------------------------------------------ |
| `add`        | Add two numbers                                  |
| `subtract`   | Subtract one number from another                 |
| `multiply`   | Multiply two numbers                             |
| `divide`     | Divide two numbers with zero-division protection |
| `percentage` | Calculate a percentage of a value                |

### 📚 Resources

Resources provide information that an MCP client can read.

| Resource                  | Description                               |
| ------------------------- | ----------------------------------------- |
| `calculator://about`      | Information about the MCP server          |
| `calculator://operations` | List of available mathematical operations |
| `calculator://examples`   | Examples of calculator operations         |

### 💬 Prompts

Prompts provide reusable instructions for AI clients.

| Prompt                | Description                                     |
| --------------------- | ----------------------------------------------- |
| `solve_math_problem`  | Helps solve a mathematical problem step by step |
| `explain_calculation` | Explains a mathematical expression              |
| `check_calculation`   | Checks whether a calculation is correct         |

---

## 🏗️ Project Structure

```text
calculations-mcp/
├── server.py
├── pyproject.toml
├── README.md
└── .gitignore
```

---

## 🚀 Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/calculations-mcp.git
cd calculations-mcp
```

Replace `YOUR_USERNAME` with your GitHub username.

### 2. Create a virtual environment

#### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

#### Windows

```powershell
python -m venv .venv
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -e .
```

Or install FastMCP directly:

```bash
pip install fastmcp
```

---

## ▶️ Run the MCP Server

Start the server with:

```bash
python server.py
```

The server will start using FastMCP's default configuration.

For development and inspection, use the FastMCP development tools available in your installed version.

---

# 🛠️ Tools

## `add`

Adds two numbers.

```text
add(10, 20)
```

Result:

```text
30
```

---

## `subtract`

Subtracts `b` from `a`.

```text
subtract(20, 5)
```

Result:

```text
15
```

---

## `multiply`

Multiplies two numbers.

```text
multiply(5, 4)
```

Result:

```text
20
```

---

## `divide`

Divides `a` by `b`.

```text
divide(100, 4)
```

Result:

```text
25
```

Division by zero is rejected:

```text
divide(10, 0)
```

The server returns an error instead of attempting an invalid calculation.

---

## `percentage`

Calculates a percentage of a value.

```text
percentage(500, 10)
```

Result:

```text
50
```

For example:

> What is 15% of 850?

The AI can call:

```text
percentage(850, 15)
```

Result:

```text
127.5
```

---

# 📚 Resources

Resources are read-only pieces of information exposed by the MCP server.

## `calculator://about`

Provides general information about the server.

Example content:

```text
Calculations 🧮

This MCP server provides mathematical calculation tools.

Available operations:
- Addition
- Subtraction
- Multiplication
- Division
- Percentage calculations
```

---

## `calculator://operations`

Provides a list of available operations.

Example:

```text
add(a, b)
subtract(a, b)
multiply(a, b)
divide(a, b)
percentage(value, percent)
```

---

## `calculator://examples`

Provides example calculations that demonstrate how the tools can be used.

---

# 💬 Prompts

Prompts are reusable instructions that MCP clients can use to guide an AI model.

## `solve_math_problem`

Creates a structured prompt for solving a mathematical problem.

Example:

```text
solve_math_problem(
    "A product costs $200 and has a 15% discount. What is the final price?"
)
```

The prompt instructs the AI to:

1. Identify the required operations.
2. Use the calculator tools when appropriate.
3. Show the calculation steps.
4. Provide the final answer clearly.

---

## `explain_calculation`

Creates a prompt for explaining a mathematical expression.

Example:

```text
explain_calculation("(10 + 5) * 2")
```

The AI is instructed to explain:

1. What the expression means.
2. The calculation steps.
3. The final result.
4. The result in beginner-friendly language.

---

## `check_calculation`

Checks whether an expected answer is correct.

Example:

```text
check_calculation(
    expression="25 * 4",
    expected_answer=100
)
```

The AI verifies the calculation and explains the result.

---

# 🔌 MCP Architecture

This project demonstrates the three important MCP primitives:

```text
                    Calculations 🧮
                           │
             ┌─────────────┼─────────────┐
             │             │             │
             ▼             ▼             ▼
           Tools       Resources       Prompts
             │             │             │
             ▼             ▼             ▼
         Perform        Provide       Guide the
       calculations     context          AI
             │             │             │
       ┌─────┼─────┐    ┌──┴──┐      ┌──┴─────────┐
       │     │     │    │     │      │            │
      add  divide  ... about examples solve_math  ...
```

### Tools

Tools are used when the AI needs to **perform an action**.

### Resources

Resources are used when the AI needs to **read information or context**.

### Prompts

Prompts are reusable templates that help the AI **perform a specific workflow**.

---

# ☁️ Deploying to FastMCP Cloud

This project is designed to be deployed to **FastMCP Cloud**.

Before deploying, make sure your project is pushed to GitHub.

```bash
git init
git add .
git commit -m "Initial Calculations MCP server"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/calculations-mcp.git
git push -u origin main
```

Then connect the GitHub repository to FastMCP Cloud and configure the server entry point to:

```text
server.py
```

FastMCP Cloud will build and host the MCP server for you.

> FastMCP Cloud's deployment UI and configuration options can change over time. Check the current FastMCP documentation when creating the deployment.

---

# 🔐 Security

This server does not require API keys or external services.

The calculator operations are deterministic and do not access:

* User files
* Databases
* External APIs
* Operating-system commands
* Environment secrets

Division by zero is explicitly handled by the server.

---

# 🧪 Example Questions

Once connected to an MCP-compatible AI client, you can ask questions such as:

> Calculate 25 + 75.

> What is 15% of 850?

> Divide 144 by 12.

> Multiply 12.5 by 8.

> Explain how `(25 + 5) * 2` is calculated.

> Check whether 45 × 12 = 540.

> Solve this math problem step by step: A shirt costs $80 and has a 25% discount. What is the final price?

---

# 🧰 Technology

* Python
* FastMCP
* Model Context Protocol (MCP)

---

# 📄 License

This project is open source. Add your preferred license here, for example:

```text
MIT License
```

If you choose the MIT License, add a `LICENSE` file to the repository.

---

# 👨‍💻 Author

Built as a learning project for exploring **Model Context Protocol (MCP)** and **FastMCP**.

If you find this project useful, consider giving the repository a ⭐ on GitHub.
