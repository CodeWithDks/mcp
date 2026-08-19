from fastmcp import FastMCP

mcp = FastMCP("Calculations 🧮")


# =========================
# TOOLS
# =========================

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


# =========================
# RESOURCES
# =========================

@mcp.resource("calculator://about")
def calculator_about() -> str:
    """Information about this calculator MCP server."""
    return """
Calculations 🧮

This MCP server provides mathematical calculation tools.

Available operations:
- Addition
- Subtraction
- Multiplication
- Division
- Percentage calculations
"""


@mcp.resource("calculator://operations")
def calculator_operations() -> str:
    """List all available mathematical operations."""
    return """
Available operations:

add(a, b)
subtract(a, b)
multiply(a, b)
divide(a, b)
percentage(value, percent)
"""


@mcp.resource("calculator://examples")
def calculator_examples() -> str:
    """Examples showing how to use the calculator."""
    return """
Examples:

add(10, 20)
=> 30

multiply(5, 4)
=> 20

divide(100, 4)
=> 25

percentage(500, 10)
=> 50
"""


# =========================
# PROMPTS
# =========================

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
If it is incorrect, provide the correct answer and explain why.
"""


# =========================
# SERVER
# =========================

if __name__ == "__main__":
    mcp.run()