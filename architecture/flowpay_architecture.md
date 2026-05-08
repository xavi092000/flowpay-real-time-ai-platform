\# FlowPay Architecture Diagram



```mermaid

flowchart TD

&#x20;   A\[Market Events] --> B\[AWS Kinesis Data Streams]

&#x20;   B --> C\[Kinesis Consumer / AWS Lambda]

&#x20;   C --> D\[Data Quality Layer]

&#x20;   D --> E\[Quantitative Risk Engine<br/>Market Risk Score]

&#x20;   E --> F\[AWS Step Functions<br/>Multi-Agent Orchestration]



&#x20;   F --> G1\[Signal Triage Agent]

&#x20;   F --> G2\[Market Analysis Agent]

&#x20;   F --> G3\[Governance Validation Agent]

&#x20;   F --> G4\[Observability Agent]



&#x20;   G1 --> H\[RAG Explanation Layer]

&#x20;   G2 --> H

&#x20;   G3 --> H

&#x20;   G4 --> H



&#x20;   H --> I\[Qdrant Vector Database]

&#x20;   H --> J\[Decision Intelligence Report]



&#x20;   J --> K\[Amazon S3 Evidence Storage]

&#x20;   K --> L\[AWS Glue Catalog]

&#x20;   L --> M\[Amazon Athena]

&#x20;   M --> N\[dbt Analytics Models]

&#x20;   N --> O\[Power BI Dashboard]



&#x20;   F --> P\[Amazon CloudWatch Metrics]

&#x20;   P --> Q\[SLO / Latency / Failure Monitoring]

