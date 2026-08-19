import json
from fastmcp import FastMCP


mcp = FastMCP("Calculations 🧮")


# ============================================================
# TOOLS
# ============================================================

@mcp.tool
def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b


@mcp.tool
def subtract(a: float, b: float) -> float:
    """Subtract b from a."""
    return a - b


@mcp.tool
def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b


@mcp.tool
def divide(a: float, b: float) -> float:
    """Divide a by b."""
    if b == 0:
        raise ValueError("Cannot divide by zero.")
    return a / b


@mcp.tool
def percentage(value: float, percent: float) -> float:
    """Calculate a percentage of a value."""
    return value * percent / 100


# ============================================================
# RESOURCES
# ============================================================

# Resource: Server information
@mcp.resource("info://server")
def server_info() -> str:
    """Get information about this calculator MCP server."""

    info = {
        "name": "Calculations 🧮",
        "version": "1.0.0",
        "description": "A basic MCP server with mathematical calculation tools.",
        "tools": [
            "add",
            "subtract",
            "multiply",
            "divide",
            "percentage",
        ],
        "resources": [
            "info://server",
            "calculator://operations",
            "calculator://examples",
        ],
        "prompts": [
            "solve_math_problem",
            "explain_calculation",
            "check_calculation",
        ],
        "author": "Deepak Singh",
    }

    return json.dumps(info, indent=2)


# Resource: Available operations
@mcp.resource("calculator://operations")
def calculator_operations() -> str:
    """Get a list of available mathematical operations."""

    operations = {
        "operations": [
            {
                "name": "add",
                "description": "Add two numbers.",
                "example": "add(10, 20) → 30",
            },
            {
                "name": "subtract",
                "description": "Subtract b from a.",
                "example": "subtract(20, 10) → 10",
            },
            {
                "name": "multiply",
                "description": "Multiply two numbers.",
                "example": "multiply(5, 4) → 20",
            },
            {
                "name": "divide",
                "description": "Divide a by b.",
                "example": "divide(100, 4) → 25",
            },
            {
                "name": "percentage",
                "description": "Calculate a percentage of a value.",
                "example": "percentage(500, 10) → 50",
            },
        ]
    }

    return json.dumps(operations, indent=2)


# Resource: Examples
@mcp.resource("calculator://examples")
def calculator_examples() -> str:
    """Get examples of calculator operations."""

    examples = {
        "examples": [
            {
                "operation": "add",
                "input": "add(10, 20)",
                "result": 30,
            },
            {
                "operation": "subtract",
                "input": "subtract(20, 10)",
                "result": 10,
            },
            {
                "operation": "multiply",
                "input": "multiply(5, 4)",
                "result": 20,
            },
            {
                "operation": "divide",
                "input": "divide(100, 4)",
                "result": 25,
            },
            {
                "operation": "percentage",
                "input": "percentage(500, 10)",
                "result": 50,
            },
        ]
    }

    return json.dumps(examples, indent=2)


# ============================================================
# PROMPTS
# ============================================================

@mcp.prompt
def solve_math_problem(problem: str) -> str:
    """Create a prompt for solving a mathematical problem."""

    return f"""
You are a mathematical assistant.

Solve the following problem carefully:

{problem}

Instructions:
1. Identify the operations required.
2. Use the available calculation tools when appropriate.
3. Show the calculation steps.
4. Give the final answer clearly.
"""


@mcp.prompt
def explain_calculation(expression: str) -> str:
    """Create a prompt for explaining a mathematical calculation."""

    return f"""
Explain the following mathematical expression:

{expression}

Provide:
1. What the expression means.
2. The calculation steps.
3. The final result.
4. A simple explanation suitable for a beginner.
"""


@mcp.prompt
def check_calculation(
    expression: str,
    expected_answer: float,
) -> str:
    """Create a prompt for checking a calculation."""

    return f"""
Check this mathematical calculation:

Expression:
{expression}

Expected answer:
{expected_answer}

Verify the result using the available calculation tools.

Explain whether the expected answer is correct.

If it is incorrect, provide the correct answer
and explain why.
"""


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=8000,
    )