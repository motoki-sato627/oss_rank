# main.py の例（抜粋）
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from aggregator import aggregate, get_rankings, get_tool_detail, get_stats

app = FastAPI(title="DevToolsRank API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

@app.post("/aggregate")
def run_aggregate(days: int = Query(90, ge=1, le=3650)):
    return aggregate(days=days, tools_csv="tools.csv")

@app.get("/rankings")
def rankings(days: int = Query(90, ge=1, le=3650)):
    return get_rankings(days=days)

@app.get("/tool/{slug}")
def tool_detail(slug: str, days: int = Query(90, ge=1, le=3650)):
    return get_tool_detail(slug=slug, days=days)

@app.get("/stats")
def stats(days: int = Query(90, ge=1, le=3650)):
    return get_stats(days=days)