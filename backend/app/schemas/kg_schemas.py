"""知识图谱 Pydantic 请求/响应模型。"""


from pydantic import BaseModel, Field


class KGEntityInput(BaseModel):
    id: str
    type: str
    name: str
    attributes: dict = Field(default_factory=dict)


class KGTripleInput(BaseModel):
    subject_id: str
    subject_type: str = ""
    predicate: str
    object_id: str
    object_type: str = ""
    confidence: float = 1.0
    source_context: str = ""


class KGBatchRequest(BaseModel):
    """批量写入三元组请求。"""
    entities: list[KGEntityInput] = Field(default_factory=list)
    triples: list[KGTripleInput] = Field(default_factory=list)
    literature_id: str | None = None


class KGBatchResponse(BaseModel):
    written_entities: int
    written_triples: int
    merged: int


class KGSearchResult(BaseModel):
    id: str
    entity_type: str
    name: str
    attributes: dict
    triple_count: int


class KGPathResult(BaseModel):
    found: bool
    path: list[dict]
    depth: int


class KGSubgraphResult(BaseModel):
    nodes: list[dict]
    edges: list[dict]
