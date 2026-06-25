"""Gurobi MCP Multi-User Backend.

A FastAPI backend that lets multiple users each run their own isolated
gurobi/mcp container against their own Gurobi Intelligence Hub credentials.
This service is a proxy: it builds and solves no optimization models itself.
"""

__version__ = "0.1.0"
