terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

resource "random_id" "suffix" {
  byte_length = 4
}

locals {
  project_name       = "flowpay"
  suffix             = random_id.suffix.hex
  data_bucket_name   = "${local.project_name}-data-${local.suffix}"
  athena_bucket_name = "${local.project_name}-athena-results-${local.suffix}"
  lambda_name        = "${local.project_name}-processor"
  glue_database_name = "${local.project_name}_db"
  sfn_name           = "${local.project_name}-decision-workflow"
}

resource "aws_kms_key" "flowpay" {
  description             = "KMS key for FlowPay encrypted resources"
  deletion_window_in_days = 7
  enable_key_rotation     = true
}

resource "aws_kms_alias" "flowpay" {
  name          = "alias/${local.project_name}-${local.suffix}"
  target_key_id = aws_kms_key.flowpay.key_id
}

resource "aws_s3_bucket" "data" {
  bucket = local.data_bucket_name
}

resource "aws_s3_bucket" "athena_results" {
  bucket = local.athena_bucket_name
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.flowpay.arn
      sse_algorithm     = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "athena_results" {
  bucket = aws_s3_bucket.athena_results.id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.flowpay.arn
      sse_algorithm     = "aws:kms"
    }
  }
}

resource "aws_s3_object" "folders" {
  for_each = toset([
    "bronze/events/",
    "silver/decisions/",
    "gold/decision_metrics/",
    "logs/",
    "replay/"
  ])

  bucket  = aws_s3_bucket.data.id
  key     = each.value
  content = ""
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.lambda_name}"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "step_functions" {
  name              = "/aws/states/${local.sfn_name}"
  retention_in_days = 7
}

resource "aws_iam_role" "lambda_role" {
  name = "${local.project_name}-lambda-role-${local.suffix}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "lambda_policy" {
  name = "${local.project_name}-lambda-policy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "${aws_cloudwatch_log_group.lambda.arn}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.data.arn,
          "${aws_s3_bucket.data.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:Encrypt",
          "kms:GenerateDataKey"
        ]
        Resource = aws_kms_key.flowpay.arn
      }
    ]
  })
}

resource "aws_iam_role" "step_functions_role" {
  name = "${local.project_name}-sfn-role-${local.suffix}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "states.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "step_functions_policy" {
  name = "${local.project_name}-sfn-policy"
  role = aws_iam_role.step_functions_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = aws_lambda_function.processor.arn
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogDelivery",
          "logs:GetLogDelivery",
          "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery",
          "logs:ListLogDeliveries",
          "logs:PutResourcePolicy",
          "logs:DescribeResourcePolicies",
          "logs:DescribeLogGroups"
        ]
        Resource = "*"
      }
    ]
  })
}

data "archive_file" "lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/lambda_placeholder.py"
  output_path = "${path.module}/lambda_placeholder.zip"
}

resource "aws_lambda_function" "processor" {
  function_name = local.lambda_name
  role          = aws_iam_role.lambda_role.arn
  handler       = "lambda_placeholder.lambda_handler"
  runtime       = "python3.12"
  filename      = data.archive_file.lambda_zip.output_path

  timeout     = 60
  memory_size = 512

  source_code_hash = data.archive_file.lambda_zip.output_base64sha256

  environment {
    variables = {
      FLOWPAY_BUCKET = aws_s3_bucket.data.bucket
      ENVIRONMENT    = "demo"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda
  ]
}

resource "aws_sfn_state_machine" "flowpay" {
  name     = local.sfn_name
  role_arn = aws_iam_role.step_functions_role.arn

  definition = jsonencode({
    Comment = "FlowPay visible multi-agent decision workflow"
    StartAt = "ValidateInput"

    States = {
      ValidateInput = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.processor.arn
          Payload = {
            step      = "validate_input"
            "state.$" = "$"
          }
        }
        OutputPath = "$.Payload"
        Next       = "RunQuantDecision"
      }

      RunQuantDecision = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.processor.arn
          Payload = {
            step      = "run_quant_decision"
            "state.$" = "$"
          }
        }
        OutputPath = "$.Payload"
        Next       = "SignalTriageAgent"
      }

      SignalTriageAgent = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.processor.arn
          Payload = {
            step      = "signal_triage"
            "state.$" = "$"
          }
        }
        OutputPath = "$.Payload"
        Next       = "MarketAnalysisAgent"
      }

      MarketAnalysisAgent = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.processor.arn
          Payload = {
            step      = "market_analysis"
            "state.$" = "$"
          }
        }
        OutputPath = "$.Payload"
        Next       = "GovernanceValidationAgent"
      }

      GovernanceValidationAgent = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.processor.arn
          Payload = {
            step      = "governance_validation"
            "state.$" = "$"
          }
        }
        OutputPath = "$.Payload"
        Next       = "ObservabilityAgent"
      }

      ObservabilityAgent = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.processor.arn
          Payload = {
            step      = "observability_check"
            "state.$" = "$"
          }
        }
        OutputPath = "$.Payload"
        Next       = "DecisionIntelligenceReport"
      }

      DecisionIntelligenceReport = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.processor.arn
          Payload = {
            step      = "generate_decision_report"
            "state.$" = "$"
          }
        }
        OutputPath = "$.Payload"
        Next       = "WriteOutputsToS3"
      }

      WriteOutputsToS3 = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.processor.arn
          Payload = {
            step      = "write_outputs"
            "state.$" = "$"
          }
        }
        OutputPath = "$.Payload"
        End        = true
      }
    }
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.step_functions.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }
}

resource "aws_glue_catalog_database" "flowpay" {
  name = local.glue_database_name
}

resource "aws_athena_workgroup" "flowpay" {
  name = "${local.project_name}-workgroup-${local.suffix}"

  configuration {
    enforce_workgroup_configuration = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.athena_results.bucket}/results/"

      encryption_configuration {
        encryption_option = "SSE_KMS"
        kms_key_arn       = aws_kms_key.flowpay.arn
      }
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${local.project_name}-lambda-errors-${local.suffix}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "FlowPay Lambda should have zero runtime errors."

  dimensions = {
    FunctionName = aws_lambda_function.processor.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "lambda_duration_slo" {
  alarm_name          = "${local.project_name}-lambda-duration-slo-${local.suffix}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  period              = 60
  extended_statistic  = "p95"
  threshold           = 5000
  alarm_description   = "FlowPay decision latency SLO: p95 below 5 seconds."

  dimensions = {
    FunctionName = aws_lambda_function.processor.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "stepfunctions_failures" {
  alarm_name          = "${local.project_name}-stepfunctions-failures-${local.suffix}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ExecutionsFailed"
  namespace           = "AWS/States"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "FlowPay Step Functions executions should not fail."

  dimensions = {
    StateMachineArn = aws_sfn_state_machine.flowpay.arn
  }
}

resource "aws_cloudwatch_dashboard" "flowpay" {
  dashboard_name = "${local.project_name}-slo-dashboard-${local.suffix}"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6

        properties = {
          title   = "FlowPay Lambda Duration p95"
          region  = "us-east-1"
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.processor.function_name, { stat = "p95" }]
          ]
          period = 60
          yAxis = {
            left = {
              label = "Milliseconds"
            }
          }
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6

        properties = {
          title   = "FlowPay Lambda Errors"
          region  = "us-east-1"
          metrics = [
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.processor.function_name, { stat = "Sum" }]
          ]
          period = 60
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6

        properties = {
          title   = "FlowPay Step Functions Failed Executions"
          region  = "us-east-1"
          metrics = [
            ["AWS/States", "ExecutionsFailed", "StateMachineArn", aws_sfn_state_machine.flowpay.arn, { stat = "Sum" }]
          ]
          period = 60
        }
      }
    ]
  })
}

output "data_bucket" {
  value = aws_s3_bucket.data.bucket
}

output "athena_results_bucket" {
  value = aws_s3_bucket.athena_results.bucket
}

output "glue_database" {
  value = aws_glue_catalog_database.flowpay.name
}

output "lambda_function_name" {
  value = aws_lambda_function.processor.function_name
}

output "step_function_arn" {
  value = aws_sfn_state_machine.flowpay.arn
}

output "athena_workgroup" {
  value = aws_athena_workgroup.flowpay.name
}

output "cloudwatch_dashboard" {
  value = aws_cloudwatch_dashboard.flowpay.dashboard_name
}