from falkordb import FalkorDB

from app.config import settings

client = FalkorDB(
    host=settings.falkordb_host,
    port=settings.falkordb_port,
    password=settings.falkordb_password,
)
graph = client.select_graph(settings.falkordb_graph)
