![AWS](https://img.shields.io/badge/AWS-Cloud-orange?style=for-the-badge&logo=amazonaws)
![Python](https://img.shields.io/badge/Python-Engineering-blue?style=for-the-badge&logo=python)
![Terraform](https://img.shields.io/badge/Terraform-IaC-623CE4?style=for-the-badge&logo=terraform)
![dbt](https://img.shields.io/badge/dbt-Analytics-FF694B?style=for-the-badge&logo=dbt)
![Power BI](https://img.shields.io/badge/PowerBI-Dashboard-F2C811?style=for-the-badge&logo=powerbi)
![RAG](https://img.shields.io/badge/AI-RAG-green?style=for-the-badge)
![Validation](https://img.shields.io/badge/Validation-100%25_PASS-success?style=for-the-badge)



# FlowPay — Real-Time Cloud AI Financial Intelligence Platform

## Executive Summary

![FlowPay Dashboard](screenshots/flowpay_dashboard.png)

FlowPay is a production-style cloud-native AI financial intelligence platform designed to simulate real-time market risk detection, multi-agent orchestration, retrieval-augmented decision intelligence, and production-grade validation workflows.

The platform combines streaming ingestion, quantitative modeling, cloud orchestration, observability, validation pipelines, and AI-driven explanations into a unified architecture.

---


## Key Production Features

- Real-time streaming ingestion using Amazon Kinesis
- Multi-agent orchestration with AWS Step Functions
- Quantitative Market Risk Score (MRS) engine
- Retrieval-Augmented Generation (RAG) explanation layer
- Adversarial validation and replay testing
- Reliability-focused architecture with observability
- Infrastructure as Code using Terraform
- Analytics engineering with dbt
- CloudWatch metrics and SLO monitoring
- Production-style evidence generation pipeline

## Core Engineering Domains

- Real-time streaming systems
- Cloud-native AI infrastructure
- Event-driven architectures
- Multi-agent orchestration
- Retrieval-Augmented Generation (RAG)
- AI validation & evaluation
- Observability & monitoring
- Infrastructure as Code (Terraform)
- Analytics engineering (dbt)
- Production reliability engineering

---

## High-Level Architecture

[View Full Architecture Diagram](architecture/flowpay_architecture.md)

```mermaid
flowchart TD
    A[Market Events] --> B[AWS Kinesis Data Streams]
    B --> C[AWS Lambda / Kinesis Consumer]
    C --> D[Data Quality Layer]
    D --> E[Quantitative Risk Engine<br/>Market Risk Score]
    E --> F[AWS Step Functions<br/>Multi-Agent Orchestration]

    F --> G1[Signal Triage Agent]
    F --> G2[Market Analysis Agent]
    F --> G3[Governance Validation Agent]
    F --> G4[Observability Agent]

    G1 --> H[RAG Explanation Layer]
    G2 --> H
    G3 --> H
    G4 --> H

    H --> I[Qdrant Vector Database]
    H --> J[Decision Intelligence Report]

    J --> K[Amazon S3 Evidence Storage]
    K --> L[AWS Glue Catalog]
    L --> M[Amazon Athena]
    M --> N[dbt Analytics Models]
    N --> O[Power BI Dashboard]

    F --> P[Amazon CloudWatch Metrics]
    P --> Q[SLO / Latency / Failure Monitoring]
```

```text
Market Events
    ↓
AWS Kinesis Data Streams
    ↓
Kinesis Consumer / Lambda Processing
    ↓
Data Quality Layer
    ↓
Quantitative Risk Engine (MRS)
    ↓
Multi-Agent Decision Layer
    ↓
RAG Explanation Layer (Qdrant)
    ↓
S3 + Athena + Glue
    ↓
dbt Analytics Models
    ↓
CloudWatch Metrics + Validation Evidence
```


## AWS Cloud Stack

- Amazon Kinesis Data Streams
- AWS Lambda
- AWS Step Functions
- Amazon S3
- Amazon Athena
- AWS Glue Catalog
- Amazon CloudWatch
- Terraform Infrastructure as Code

---

## Production-Grade Validation

FlowPay includes a full validation and reliability framework:

- Adversarial replay testing
- Data quality validation
- Failure handling validation
- Latency & SLO validation
- Event replay systems
- Quantitative calibration
- RAG evaluation
- Streaming validation
- Global evidence generation

---
## Validation Results

| Validation Area | Result |
|---|---|
| Adversarial Testing | PASSED |
| Data Quality Validation | PASSED |
| Failure Handling Validation | PASSED |
| Streaming Validation | PASSED |
| RAG Evaluation | PASSED |
| SLO Validation (<5s) | PASSED |
| Global Validation Pass Rate | 100% |

---

## Performance Metrics

| Metric | Result |
|---|---|
| Average Latency | ~1.6s |
| P95 Latency | ~2.1s |
| SLO Target (<5s) | PASSED |
| Infrastructure Failures | 0 |

---

## Observability & Reliability

- CloudWatch metrics publishing
- Validation evidence generation
- Failure replay systems
- Adversarial scenario testing
- Decision quality evaluation
- Reliability-oriented architecture

---

## Infrastructure as Code

Infrastructure deployment is managed using Terraform.

Infrastructure components include:

- Kinesis Data Streams
- Lambda deployment
- CloudWatch metrics
- IAM policies
- S3 storage
- Athena integration

---

## Analytics Engineering

FlowPay includes a dbt analytics layer with:

- models
- tests
- snapshots
- macros
- lineage-ready transformations

---
## Technical Skills Demonstrated

- AWS Cloud Architecture
- Real-Time Streaming Systems
- Multi-Agent AI Systems
- Retrieval-Augmented Generation (RAG)
- Infrastructure as Code (Terraform)
- dbt Analytics Engineering
- Cloud Observability
- Validation Engineering
- Reliability Engineering
- Python Data Engineering

---

## Production Reliability Signals

- P95 latency tracking
- SLO validation under 5 seconds
- Adversarial replay testing
- Failure handling validation
- Replay-based validation workflows
- CloudWatch observability
- Evidence generation pipeline
- Infrastructure reproducibility with Terraform
- dbt-based analytics validation

---


## Why This Project Matters

FlowPay demonstrates the intersection of:

- AI Engineering
- Cloud Data Engineering
- Reliability Engineering
- Streaming Architectures
- LLMOps
- Observability
- Decision Intelligence Systems

---

## How to Run / Reproduce

This repository is designed as a portfolio-grade reference implementation.  
Some AWS resources may require account-specific configuration before execution.

### Local Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

## Evidence & Validation

Validation evidence and evaluation summaries are available in the `/evidence` directory.

---

## Project Structure

```text
flowpay-real-time-ai-platform/
│
├── architecture/        # System architecture diagrams
├── data/                # Replay and validation datasets
├── docs/                # Documentation and README versions
├── evidence/            # Validation evidence and reports
├── flowpay_dbt/         # dbt analytics engineering layer
├── infra/               # Terraform infrastructure
├── screenshots/         # Dashboard and architecture screenshots
│
├── flowpay_quant_engine.py
├── flowpay_decision_agents.py
├── flowpay_validation_runner.py
├── flowpay_rag_with_quant.py
├── flowpay_observability.py
│
└── README.md
```
## Local Execution

Run the complete FlowPay demonstration:

```bash
python flowpay_full_demo.py
```

Run the global validation pipeline:

```bash
python flowpay_validation_runner.py
```

Run adversarial replay testing:

```bash
python flowpay_adversarial_event_replay.py
```

Run streaming replay validation:

```bash
python flowpay_30s_event_replay_validation.py
```

---

Author

Felix Brillant
AI / Cloud Data Engineering