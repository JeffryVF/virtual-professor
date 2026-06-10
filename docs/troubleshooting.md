# RAG Troubleshooting Guide — Virtual Professor

> Diagnóstico de errores críticos, impacto en producción y plan de remediación.
> Versión: 1.0 — Junio 2026

---

## Tabla de Contenidos

1. [CRIT-01: Sin threshold de relevancia en retrieval](#crit-01-sin-threshold-de-relevancia-en-retrieval)
2. [CRIT-02: Sin reranker en pipeline de retrieval](#crit-02-sin-reranker-en-pipeline-de-retrieval)
3. [CRIT-03: Sin trazabilidad de fuentes (citations)](#crit-03-sin-trazabilidad-de-fuentes-citations)
4. [Matriz de Priorización](#matriz-de-priorización)
5. [Recomendaciones por Release](#recomendaciones-por-release)

---

## CRIT-01: Sin threshold de relevancia en retrieval

### Síntoma

El retriever siempre devuelve `top_k=5` chunks, incluso cuando ningún chunk es realmente relevante para la consulta. Esto fuerza al LLM a recibir contexto ruidoso o directamente incorrecto.

### Código afectado

`services/rag.py:23` — `retriever = index.as_retriever(similarity_top_k=top_k)`

### Causa raíz

No hay un filtro por score de similitud. Qdrant devuelve los 5 vectores más cercanos por distancia coseno, pero si la distancia es alta (poca similitud), igual se inyectan en el prompt del LLM.

### Impacto en producción

| Escenario | Consecuencia |
|-----------|-------------|
| Alumno pregunta algo fuera del knowledge base | El LLM recibe chunks irrelevantes y alucina una respuesta basada en ruido |
| Profesor con documentos variados | Chunks de temas distintos contaminan la respuesta |
| Embedding de consulta pobre (e.g., query muy corta) | Cualquier chunk pasa el corte por falta de un mínimo de similitud |

### Diagnóstico

```python
# Verificar scores actuales en una consulta de prueba
from qdrant_client import AsyncQdrantClient

aclient = AsyncQdrantClient(url="http://qdrant:6333")
result = await aclient.search(
    collection_name="profesor_matematicas",
    query_vector=[...],  # embedding de consulta
    limit=5,
    with_payload=True,
    with_vectors=False,
)
for scored in result:
    print(f"Score: {scored.score:.4f} — {scored.payload.get('document_id')}")
```

### Remedio

```python
MIN_RELEVANCE_SCORE = 0.75  # threshold calibrable por profesor

nodes = await retriever.aretrieve(query)
nodes = [n for n in nodes if n.score >= MIN_RELEVANCE_SCORE]

if not nodes:
    return []  # → pipeline retorna "no tengo información en mis fuentes"
```

### Validación

- [ ] Consulta con término existente → score > 0.75, pasa el filtro
- [ ] Consulta con término inexistente → sin chunks, respuesta graceful
- [ ] Consulta ambigua borderline → ajustar threshold según validación con dataset real

---

## CRIT-02: Sin reranker en pipeline de retrieval

### Síntoma

El orden de los chunks se define únicamente por similitud coseno del embedding denso. Un chunk con alta similitud léxica pero poca relevancia semántica puede aparecer primero, sesgando la respuesta del LLM.

### Código afectado

`services/rag.py:23-24` — Retrieval directo sin reranking post-proceso.

### Causa raíz

Los embeddings densos (`nomic-embed-text`) capturan semántica general pero no discriminan fine-grained relevance. El top-1 de la búsqueda densa frecuentemente no es el chunk más útil para responder la pregunta.

### Impacto en producción

| Escenario | Consecuencia |
|-----------|-------------|
| Consulta específica "fórmula de la derivada de x²" | Chunk genérico sobre "qué son las derivadas" aparece primero, el chunk con la fórmula exacta queda 3ro o 4to |
| Consulta multi-intención | Chunks mezclados sin orden de relevancia real |
| Profesor con mucho contenido similar | Dense retrieval solo no logra rankear por utilidad |

### Diagnóstico

Métrica objetivo: **MRR@10** (Mean Reciprocal Rank). Un reranker debe mejorar el MRR en al menos 15-25 puntos porcentuales.

```bash
# Evaluación offline: samplear 100 queries reales
# Calcular HitRate@5 y MRR@10 antes y después del reranker
```

### Remedio

Integrar reranker liviano post-retrieval:

```python
# Opción A — BGE Reranker (local, CPU-friendly)
from rerankers import Reranker

reranker = Reranker("BAAI/bge-reranker-v2-m3", model_type="cross-encoder")
TOP_K_RETRIEVAL = 20  # recuperar más, rerankear mejor
TOP_K_FINAL = 5

# En el pipeline:
raw_nodes = await retriever.aretrieve(query, similarity_top_k=TOP_K_RETRIEVAL)
if raw_nodes:
    passages = [n.get_content() for n in raw_nodes]
    results = reranker.rank(query=query, docs=passages)
    top_indices = [r.index for r in results[:TOP_K_FINAL]]
    nodes = [raw_nodes[i] for i in top_indices]
```

```python
# Opción B — Qdrant + sparse vectors (no requiere servicio extra)
# Qdrant soporta hybrid search con BM25 desde v1.7
# Crear colección con sparse_vector_config + dense_vector_config
# Query con prefusion (RRF) para combinar resultados
```

### Validación

- [ ] Evaluación offline: MRR@10 mejora respecto a solo dense retrieval
- [ ] Latencia: reranker no agrega más de 200ms al pipeline total
- [ ] Caso borde: consulta corta de 2-3 palabras sigue funcionando

---

## CRIT-03: Sin trazabilidad de fuentes (citations)

### Síntoma

El LLM genera respuestas sin indicar de qué documento o sección proviene la información. El estudiante no puede verificar ni profundizar en las fuentes.

### Código afectado

`services/llm.py:17-21` — El contexto se pasa como texto plano sin metadata de procedencia.
`services/rag.py:26` — `node.get_content()` devuelve solo el texto, descartando metadata.

### Causa raíz

El pipeline construye el contexto como `"\n\n---\n\n".join(context_chunks)` — texto plano. No se pasa metadata de fuente (documento, página, sección), y el system prompt no instruye al LLM a citar.

### Impacto en producción

| Escenario | Consecuencia |
|-----------|-------------|
| Estudiante quiere verificar un dato | No puede — no hay referencia a la fuente |
| Contenido incorrecto en un documento | Imposible depurar qué documento causó el error |
| Requisito de compliance académico | Falla: en educación es obligatorio citar fuentes |
| Confianza del usuario | El profesor "suena" a que sabe, pero no hay transparencia |

### Diagnóstico

```bash
# Verificar qué payload viaja en Qdrant
curl -X POST http://localhost:6333/collections/{collection}/points/search \
  -H "Content-Type: application/json" \
  -d '{
    "vector": [0.1, 0.2, ...],
    "limit": 1,
    "with_payload": true
  }'
# Observar que solo tiene document_id y professor_collection
```

### Remedio

**Fase 1 — Metadata enriquecida en ingestión (`ingestion.py`):**

```python
# Enriquecer nodos antes de indexar
for node in nodes:
    node.metadata.update({
        "document_id": document_id,
        "document_name": document_filename,  # nuevo
        "page_number": node.metadata.get("page_label", ""),  # si el reader lo provee
        "chunk_index": i,  # nuevo
        "total_chunks": len(nodes),  # nuevo
        "professor_collection": professor_collection,
    })
```

**Fase 2 — Pasar metadata al LLM (`rag.py` + `llm.py`):**

```python
# rag.py — devolver tuplas (texto, metadata)
async def retrieve_context(...) -> list[tuple[str, dict]]:
    ...
    return [(n.get_content(), n.metadata) for n in nodes]
```

```python
# llm.py — construir contexto con referencias
context_parts = []
for i, (text, meta) in enumerate(context_chunks, 1):
    source = meta.get("document_name", "Unknown")
    page = meta.get("page_number", "")
    ref = f"[{i}]"
    context_parts.append(f"{ref} (Source: {source}{', p. ' + page if page else ''})\n{text}")

context_str = "\n\n".join(context_parts)
```

**Fase 3 — System prompt con instrucción de citado:**

```python
f"{system_prompt}\n\n"
f"Use the following knowledge to answer. "
f"ALWAYS cite your sources using bracketed numbers like [1], [2] "
f"at the end of each claim. E.g.: "
f"\"The derivative of x² is 2x [1]. This is because...\"\n\n"
f"Knowledge:\n{context_str}"
```

**Fase 4 — Parseo de citas en la respuesta final:**

Opcional: extraer `[N]` de la respuesta y devolverlas como metadato al frontend para mostrar tooltips con "Ver fuente".

### Validación

- [ ] Respuesta del LLM contiene citas `[1]`, `[2]` cuando corresponde
- [ ] Cada cita tiene metadata traducible (documento + página)
- [ ] Si chunks son irrelevantes, el LLM *no* inventa citas
- [ ] Frontend puede mostrar tooltip/panel con la fuente al hacer clic en `[1]`

---

## Matriz de Priorización

| ID | Issue | Impacto | Esfuerzo | Dependencias | Prioridad |
|----|-------|---------|----------|-------------|-----------|
| CRIT-01 | Threshold de relevancia | Alto | Bajo (< 1d) | Ninguna | **P0 — Inmediata** |
| CRIT-02 | Reranker | Alto | Medio (2-3d) | CRIT-01 | **P1 — Siguiente** |
| CRIT-03 | Citations | Alto | Medio (3-4d) | CRIT-01 + CRIT-02 | **P1 — Siguiente** |

### Criterios

- **P0**: Bugs o ausencias que causan alucinaciones, respuestas incorrectas o violación de requisitos core.
- **P1**: Funcionalidad crítica para credibilidad del producto, diferenciación en mercado y confianza del usuario.
- **P2**: Mejora de calidad, monitoreo, observabilidad (fuera de este documento).

---

## Recomendaciones por Release

### Release 1 — "No hacer daño" (CRIT-01)

Duración estimada: **1-2 días**

- Threshold de relevancia configurable por profesor
- Respuesta graceful cuando no hay contexto: *"No encontré información sobre eso en mis fuentes"*
- Logging de consultas sin resultados para auditoría

### Release 2 — "Respuestas confiables" (CRIT-02 + CRIT-03)

Duración estimada: **4-6 días**

- Reranker local (BGE) integrado en pipeline
- Metadata enriquecida en chunks de Qdrant
- Citation tracking en respuestas del LLM
- Evaluación offline de MRR@10 vs baseline

---

> **Próximo paso recomendado**: implementar CRIT-01 como PR independiente. Es el de mayor impacto con menor esfuerzo, y destraba los otros dos.
