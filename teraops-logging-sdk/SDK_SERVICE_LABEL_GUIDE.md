# TeraOps SDK — Service Label Validation Guide

## Overview

The TeraOps Python SDK validates every log before sending it to the TeraOps API. The `service_label` field is the **single most important field** — it's the only field that will cause a log to be **rejected** (dropped entirely). All other missing fields result in soft warnings (`_format_issues`) but the log still gets sent.

---

## Log Validation Flowchart

```
                        +---------------------+
                        |   Log arrives from   |
                        |   OTEL pipeline      |
                        +----------+----------+
                                   |
                                   v
                    +-----------------------------+
                    |  STEP 1: service_label      |
                    |  present & non-empty?        |
                    +-----------------------------+
                           |              |
                          NO             YES
                           |              |
                           v              v
                  +----------------+   +---------------------------+
                  |  LOG REJECTED  |   |  STEP 2: Build log entry  |
                  |  (dropped,     |   |  timestamp, message,      |
                  |   never sent)  |   |  severity                 |
                  +----------------+   +-------------+-------------+
                                                     |
                                                     v
                                       +---------------------------+
                                       |  STEP 3: Validate &       |
                                       |  Normalize                 |
                                       |  - severity uppercase     |
                                       |  - message size check     |
                                       |  - secret redaction       |
                                       +-------------+-------------+
                                                     |
                                                     v
                                       +---------------------------+
                                       |  STEP 4: Auto-enrich      |
                                       |  hostname, pid, runtime,  |
                                       |  os, arch (free)          |
                                       +-------------+-------------+
                                                     |
                                                     v
                                       +---------------------------+
                                       |  STEP 5: Filter attrs     |
                                       |  - redact secrets         |
                                       |  - enforce size limits    |
                                       |  - max 50 attributes      |
                                       +-------------+-------------+
                                                     |
                                                     v
                                       +---------------------------+
                                       |  STEP 6: Check mandatory  |
                                       |  base fields              |
                                       |  - app_name               |
                                       |  - user_id                |
                                       |  - customer_id            |
                                       |                           |
                                       |  Missing? -> soft warning |
                                       |  (log still sent)         |
                                       +-------------+-------------+
                                                     |
                                                     v
                                       +---------------------------+
                                       |  STEP 7: Check AI label   |
                                       |  context fields           |
                                       |  (only if service_label   |
                                       |   is one of 6 AI labels)  |
                                       |                           |
                                       |  Missing? -> soft warning |
                                       |  (log still sent)         |
                                       +-------------+-------------+
                                                     |
                                                     v
                                       +---------------------------+
                                       |  STEP 8: Tag log          |
                                       |                           |
                                       |  _formatted = true/false  |
                                       |  _format_issues = [...]   |
                                       +-------------+-------------+
                                                     |
                                                     v
                                       +---------------------------+
                                       |  STEP 9: Buffer & Send    |
                                       |  to TeraOps API           |
                                       +---------------------------+
```

---

## Field Requirement Levels

| Level | Behavior | Example |
|---|---|---|
| **HARD REJECT** | Log is dropped, never sent to TeraOps | Missing `service_label` |
| **SOFT WARNING** | Log is sent but tagged `_formatted: false` with `_format_issues` list | Missing `app_name`, `user_id`, `customer_id`, or AI label context fields |
| **AUTO-ENRICHED** | SDK adds these automatically, customer does nothing | `hostname`, `pid`, `runtime`, `os`, `arch` |

---

## Mandatory Base Fields (All Labels)

These 3 fields are expected on **every log**, regardless of label:

| Field | Type | Description | If Missing |
|---|---|---|---|
| `app_name` | string | Name of the application (e.g. `"customer-llm-app"`) | `_format_issues: ["missing_app_name"]` |
| `user_id` | string/int | ID of the user making the request | `_format_issues: ["missing_user_id"]` |
| `customer_id` | string/int | ID of the customer/tenant/company | `_format_issues: ["missing_customer_id"]` |

**Note:** These are soft warnings. The log is still sent — it just gets `_formatted: false` so TeraOps can flag it in the dashboard.

---

## The 6 AI Service Labels

These are the **predefined AI labels** that map directly to AWS CUR `cost_sub_category`. Each has its own required context fields.

---

### 1. `inference`

**What it covers:** Direct LLM calls — text generation, chat completions, summarization, Q&A

**AWS Services:** Bedrock `InvokeModel`, SageMaker inference endpoints

**Required context fields:**

| Field | Type | Description | Unit |
|---|---|---|---|
| `inference_model` | string | Model ID used (e.g. `"anthropic.claude-3-sonnet-20240229-v1:0"`) | — |

**Recommended extra fields:**

| Field | Type | Description | Unit |
|---|---|---|---|
| `input_tokens` | int | Tokens sent to the model | tokens |
| `output_tokens` | int | Tokens generated by the model | tokens |
| `total_tokens` | int | input_tokens + output_tokens | tokens |
| `prompt_length` | int | Character count of the prompt | characters |
| `duration_ms` | float | Request duration | milliseconds |

**Example log:**
```json
{
  "service_label": "inference",
  "app_name": "customer-llm-app",
  "user_id": 3028,
  "customer_id": 318,
  "inference_model": "anthropic.claude-3-sonnet-20240229-v1:0",
  "input_tokens": 25,
  "output_tokens": 150,
  "total_tokens": 175,
  "duration_ms": 2340.5,
  "endpoint": "/chatbot/message",
  "status": 200
}
```

**API endpoint in demo app:** `POST /chatbot/message`

---

### 2. `rag`

**What it covers:** Retrieval-Augmented Generation — Knowledge Base queries that retrieve context from a vector store then generate an answer

**AWS Services:** Bedrock `RetrieveAndGenerate`, Bedrock Knowledge Bases, OpenSearch Serverless (vector store), Titan Embeddings

**Required context fields:**

| Field | Type | Description | Unit |
|---|---|---|---|
| `inference_model` | string | Model ARN used for generation | — |
| `embedding_model` | string | Embedding model used for vector search (e.g. `"amazon.titan-embed-text-v1"`) | — |
| `vector_database` | string | Vector store type (e.g. `"opensearch-serverless"`) | — |

**Recommended extra fields:**

| Field | Type | Description | Unit |
|---|---|---|---|
| `knowledge_base_id` | string | Bedrock Knowledge Base ID | — |
| `embedding_tokens` | int | Tokens consumed by the embedding call (query vectorization) | tokens |
| `input_tokens` | int | Tokens sent to the inference model | tokens |
| `output_tokens` | int | Tokens generated by the inference model | tokens |
| `total_tokens` | int | input_tokens + output_tokens | tokens |
| `num_citations` | int | Number of citations returned | count |
| `num_retrieved_references` | int | Number of source chunks retrieved from vector store | count |
| `duration_ms` | float | Request duration | milliseconds |

**Token cost breakdown for RAG:**
```
RAG call cost = Embedding cost + Inference cost

Embedding cost:
  - Model: amazon.titan-embed-text-v1
  - Unit: input tokens only (no output tokens for embeddings)
  - Measured by: embedding_tokens
  - Pricing: ~$0.0001 per 1,000 tokens

Inference cost:
  - Model: claude-3-haiku (or configured model)
  - Unit: input tokens + output tokens
  - Measured by: input_tokens, output_tokens
  - Pricing: varies by model
```

**Example log:**
```json
{
  "service_label": "rag",
  "app_name": "customer-llm-app",
  "user_id": 3028,
  "customer_id": 318,
  "inference_model": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
  "embedding_model": "amazon.titan-embed-text-v1",
  "vector_database": "opensearch-serverless",
  "knowledge_base_id": "Z8OKJWDDOE",
  "embedding_tokens": 12,
  "input_tokens": 12,
  "output_tokens": 85,
  "total_tokens": 97,
  "num_citations": 3,
  "num_retrieved_references": 5,
  "duration_ms": 3200.0,
  "endpoint": "/chatbot/rag",
  "status": 200
}
```

**API endpoint in demo app:** `POST /chatbot/rag`

---

### 3. `image_generation`

**What it covers:** AI image generation from text prompts

**AWS Services:** Bedrock `InvokeModel` with Titan Image Generator, Stability AI models

**Required context fields:**

| Field | Type | Description | Unit |
|---|---|---|---|
| `inference_model` | string | Image model ID (e.g. `"amazon.titan-image-generator-v2:0"`) | — |

**Recommended extra fields:**

| Field | Type | Description | Unit |
|---|---|---|---|
| `image_count` | int | Number of images generated per request (typically 1) | count |
| `image_width` | int | Image width | pixels |
| `image_height` | int | Image height | pixels |
| `prompt_length` | int | Character count of the text prompt | characters |
| `duration_ms` | float | Request duration | milliseconds |

**Example log:**
```json
{
  "service_label": "image_generation",
  "app_name": "customer-llm-app",
  "user_id": 3027,
  "customer_id": 317,
  "inference_model": "amazon.titan-image-generator-v2:0",
  "image_count": 1,
  "image_width": 512,
  "image_height": 512,
  "prompt_length": 45,
  "duration_ms": 8124.0,
  "endpoint": "/ai/generate-image",
  "status": 200
}
```

**API endpoint in demo app:** `POST /ai/generate-image`

---

### 4. `data_processing`

**What it covers:** Text analysis, NLP, translation — any AI service that processes data without generating new content

**AWS Services:** Amazon Comprehend (sentiment, entities, key phrases), Amazon Translate, Amazon Textract, Amazon Rekognition

**Required context fields:**

| Field | Type | Description | Unit |
|---|---|---|---|
| `ai_service` | string | AWS service used (e.g. `"comprehend"`, `"translate"`) | — |
| `operation` | string | API operation called (e.g. `"DetectSentiment"`, `"TranslateText"`) | — |

**Recommended extra fields:**

| Field | Type | Description | Unit |
|---|---|---|---|
| `processing_units` | int | Amount of data processed | see `processing_unit_type` |
| `processing_unit_type` | string | Unit of measurement: `"characters"`, `"pages"`, `"images"`, `"seconds"` | — |
| `prompt_length` | int | Character count of input text | characters |
| `duration_ms` | float | Request duration | milliseconds |

**Processing unit types by AWS service:**

| AWS Service | processing_unit_type | How to calculate processing_units |
|---|---|---|
| Comprehend (DetectSentiment, DetectEntities, DetectKeyPhrases) | `characters` | `len(input_text)` — min 3 units per request |
| Translate (TranslateText) | `characters` | `len(input_text)` |
| Textract (AnalyzeDocument) | `pages` | Number of pages processed |
| Rekognition (DetectLabels, DetectFaces) | `images` | Number of images processed |
| Transcribe (StartTranscriptionJob) | `seconds` | Duration of audio in seconds |

**Example log (Comprehend):**
```json
{
  "service_label": "data_processing",
  "app_name": "customer-llm-app",
  "user_id": 3028,
  "customer_id": 318,
  "ai_service": "comprehend",
  "operation": "DetectSentiment+DetectEntities+DetectKeyPhrases",
  "processing_units": 52,
  "processing_unit_type": "characters",
  "sentiment": "POSITIVE",
  "num_entities": 2,
  "num_key_phrases": 3,
  "duration_ms": 450.0,
  "endpoint": "/ai/analyze",
  "status": 200
}
```

**Example log (Translate):**
```json
{
  "service_label": "data_processing",
  "app_name": "customer-llm-app",
  "user_id": 3029,
  "customer_id": 319,
  "ai_service": "translate",
  "operation": "TranslateText",
  "processing_units": 37,
  "processing_unit_type": "characters",
  "source_language": "en",
  "target_language": "es",
  "duration_ms": 320.0,
  "endpoint": "/ai/analyze",
  "status": 200
}
```

**API endpoint in demo app:** `POST /ai/analyze` (with `action: "analyze"` or `action: "translate"`)

---

### 5. `compute`

**What it covers:** AI compute operations — agent orchestration, model training, inference endpoints, batch processing

**AWS Services:** Bedrock Agents (`InvokeAgent`), SageMaker (Training, Endpoints, Processing, Notebooks), Step Functions, Lambda-based AI pipelines

**Required context fields:**

| Field | Type | Description | Unit |
|---|---|---|---|
| `compute_type` | string | Type of compute (see subtypes table below) | — |

**`compute_type` subtypes and their key fields:**

| compute_type | What it is | Key fields to send |
|---|---|---|
| `agent` | Bedrock Agent calls | `compute_resource`, `inference_model`, `duration_ms` |
| `training` | SageMaker training jobs | `compute_hours`, `compute_resource`, `duration_ms` |
| `endpoint` | SageMaker model endpoints | `compute_hours`, `input_tokens`, `output_tokens`, `duration_ms` |
| `notebook` | SageMaker notebooks | `compute_hours`, `duration_ms` |
| `pipeline` | MLOps pipelines | `compute_hours`, `duration_ms` |
| `processing` | SageMaker processing jobs | `compute_hours`, `duration_ms` |
| `batch_transform` | Batch inference jobs | `compute_hours`, `input_tokens`, `output_tokens`, `duration_ms` |

**Note on tokens:** Bedrock `InvokeAgent` does not return token counts in its response. For `compute_type=agent`, `input_tokens`/`output_tokens`/`total_tokens` will be absent — this is an AWS API limitation, not a logging gap.

**Note on `compute_hours`:** Only applicable for long-running compute (training, endpoints, notebooks, pipelines, processing). Not applicable for agent calls which are request/response.

**Recommended extra fields (all compute types):**

| Field | Type | Description | Unit |
|---|---|---|---|
| `compute_resource` | string | Resource identifier (Agent ID, job name, endpoint name) | — |
| `compute_hours` | float | Compute time consumed (for training/endpoint/notebook) | hours |
| `inference_model` | string | Model used | — |
| `input_tokens` | int | Tokens sent (when available) | tokens |
| `output_tokens` | int | Tokens generated (when available) | tokens |
| `total_tokens` | int | input + output tokens | tokens |
| `agent_id` | string | Bedrock Agent ID | — |
| `agent_alias_id` | string | Bedrock Agent Alias ID | — |
| `duration_ms` | float | Request duration | milliseconds |

**Example log (agent):**
```json
{
  "service_label": "compute",
  "app_name": "customer-llm-app",
  "user_id": 3028,
  "customer_id": 318,
  "compute_type": "agent",
  "compute_resource": "FJ7TW5ADB8",
  "inference_model": "anthropic.claude-3-sonnet-20240229-v1:0",
  "agent_id": "FJ7TW5ADB8",
  "agent_alias_id": "Y0XOXSYVWZ",
  "duration_ms": 5400.0,
  "endpoint": "/ai/agent",
  "status": 200
}
```

**Example log (training):**
```json
{
  "service_label": "compute",
  "app_name": "ml-training-app",
  "user_id": 2001,
  "customer_id": 201,
  "compute_type": "training",
  "compute_resource": "my-bert-finetune-job",
  "compute_hours": 2.5,
  "duration_ms": 9000000,
  "status": 200
}
```

**API endpoint in demo app:** `POST /ai/agent` (compute_type=agent)

---

### 6. `storage`

**What it covers:** AI-related data storage operations — storing embeddings, training data, model artifacts, vector DB writes

**AWS Services:** S3, OpenSearch Serverless (writes), DynamoDB, EFS

**Required context fields:**

| Field | Type | Description | Unit |
|---|---|---|---|
| `storage_type` | string | Type of storage (e.g. `"s3"`, `"opensearch"`, `"dynamodb"`) | — |

**Recommended extra fields:**

| Field | Type | Description | Unit |
|---|---|---|---|
| `storage_operation` | string | Operation type (e.g. `"put"`, `"get"`, `"delete"`, `"index"`) | — |
| `storage_bucket` | string | S3 bucket or collection name | — |
| `object_size_bytes` | int | Size in bytes. **Include on every operation:** upload=file size, list=total size of listed objects, delete=size of deleted object, get=downloaded size | bytes |
| `object_key` | string | S3 key or object path | — |
| `duration_ms` | float | Request duration | milliseconds |

**Example log:**
```json
{
  "service_label": "storage",
  "app_name": "customer-llm-app",
  "user_id": 3028,
  "customer_id": 318,
  "storage_type": "s3",
  "storage_operation": "put",
  "storage_bucket": "my-ai-training-data",
  "object_size_bytes": 1048576,
  "duration_ms": 230.0,
  "endpoint": "/storage/upload",
  "status": 200
}
```

**API endpoint in demo app:** Not yet created

---

## Application Labels (Custom)

Beyond the 6 AI labels, you can use **any custom string** as a `service_label`. These are called **application labels** — they don't have required context fields, so the SDK won't check for anything beyond the base fields.

**Common examples:**

| Label | Use Case |
|---|---|
| `authentication` | Login, signup, token refresh, failed auth attempts |
| `billing` | Payment processing, subscription management |
| `notification` | Email, SMS, push notifications |
| `monitoring` | Health checks, heartbeats |
| `admin` | Admin panel operations |

**Example (authentication):**
```json
{
  "service_label": "authentication",
  "app_name": "customer-llm-app",
  "user_id": 3028,
  "customer_id": 318,
  "endpoint": "/auth/login",
  "method": "POST",
  "status": 200,
  "duration_ms": 45.0
}
```

Application labels get the same base field checks (`app_name`, `user_id`, `customer_id`) but no AI context field checks.

---

## What Happens When...

### No `service_label` at all

```
Result: LOG REJECTED (dropped, never sent)

SDK output (debug mode):
  "Log rejected — missing or empty 'service_label' attribute.
   Every log must include a 'service_label' (e.g. 'inference', 'rag', 'authentication')."

The log is silently dropped. It never reaches the TeraOps API.
```

### Empty `service_label` (e.g. `""` or `"  "`)

```
Result: LOG REJECTED (same as missing)

The SDK trims whitespace and checks — empty strings are treated as missing.
```

### `service_label` present but missing base fields

```
Example: service_label="inference" but no user_id, no customer_id

Result: LOG SENT with warnings

{
  "_formatted": false,
  "_format_issues": ["missing_user_id", "missing_customer_id"]
}

The log reaches TeraOps but is flagged as improperly formatted.
```

### AI label missing required context fields

```
Example: service_label="rag" but no embedding_model, no vector_database

Result: LOG SENT with warnings

{
  "_formatted": false,
  "_format_issues": ["missing_embedding_model", "missing_vector_database"]
}

The log reaches TeraOps but is flagged.
```

### Custom/application label (no AI context needed)

```
Example: service_label="authentication" with all base fields

Result: LOG SENT, fully formatted

{
  "_formatted": true,
  "_format_issues": []
}
```

### Everything perfect (AI label + all fields)

```
Example: service_label="inference" with app_name, user_id, customer_id, inference_model

Result: LOG SENT, fully formatted

{
  "_formatted": true,
  "_format_issues": []
}
```

---

## Summary Table: All Labels & Their Fields

| Label | Required Context Fields | Typical AWS Service | Unit of Measurement | Demo App Status |
|---|---|---|---|---|
| `inference` | `inference_model` | Bedrock InvokeModel | tokens (input + output) | WORKING |
| `rag` | `inference_model`, `embedding_model`, `vector_database` | Bedrock RetrieveAndGenerate | tokens (embedding + inference) | WORKING |
| `image_generation` | `inference_model` | Bedrock InvokeModel (Titan Image) | images (count) | WORKING |
| `data_processing` | `ai_service`, `operation` | Comprehend, Translate | characters, pages, images, seconds | WORKING |
| `compute` | `compute_type` | Bedrock InvokeAgent | duration / invocations | NEEDS CONFIG |
| `storage` | `storage_type` | S3, OpenSearch, DynamoDB | bytes | NOT CREATED |

---

## Validation Priority

```
P0 (HARD) ─── service_label missing?     ──> REJECT (log dropped)
P0 (SOFT) ─── app_name missing?          ──> WARN (_format_issues)
P0 (SOFT) ─── user_id missing?           ──> WARN (_format_issues)
P0 (SOFT) ─── customer_id missing?       ──> WARN (_format_issues)
P0 (SOFT) ─── AI context field missing?  ──> WARN (_format_issues)
P0 (AUTO) ─── secrets in message/attrs?  ──> REDACT (***REDACTED***)
P0 (AUTO) ─── message > 64KB?            ──> TRUNCATE
P0 (AUTO) ─── attribute > 4KB?           ──> TRUNCATE
P0 (AUTO) ─── > 50 attributes?           ──> DROP extras
```

---

## SDK Auto-Enrichment (Free)

These fields are added to **every log automatically** by the SDK. The customer doesn't need to do anything:

| Field | Example | Source |
|---|---|---|
| `hostname` | `ip-172-31-25-100` | `socket.gethostname()` |
| `process_id` | `138794` | `os.getpid()` |
| `runtime` | `Python 3.11.6` | `platform.python_version()` |
| `os` | `Linux` | `platform.system()` |
| `arch` | `x86_64` | `platform.machine()` |
| `_sdk_version` | `0.1.0` | SDK version |
| `_formatted` | `true/false` | Validation result |
| `_format_issues` | `["missing_user_id"]` | List of validation issues |
