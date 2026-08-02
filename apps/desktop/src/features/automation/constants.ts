import type { AutomationTriggerType } from '../../api/types'

export const TRIGGER_TYPES: AutomationTriggerType[] = [
  'manual',
  'timer',
  'cron',
  'asset_imported',
  'asset_updated',
  'asset_published',
  'review_approved',
  'review_rejected',
  'workflow_completed',
  'workflow_failed',
  'agent_completed',
  'project_created',
  'project_opened',
  'research_completed',
  'image_generated',
  'video_generated',
]

export const CONDITION_TYPES = [
  'project_id',
  'studio',
  'asset_type',
  'agent_id',
  'workflow_id',
  'hour',
  'user',
  'tags',
  'metadata',
  'asset_id',
]

export const CONDITION_OPERATORS = [
  'equals',
  'not_equals',
  'in',
  'contains',
  'not_contains',
  'greater_than',
  'less_than',
  'between',
  'exists',
  'not_exists',
  'graph_relationship_exists',
]

/** Executable actions are submitted to the scheduler; state actions only mutate kernel records. */
export const ACTION_TYPES = [
  'run_planner',
  'queue_workflow',
  'start_runtime',
  'generate_asset',
  'generate_image',
  'generate_video',
  'run_review',
  'send_notification',
  'create_task',
  'create_report',
  'archive_asset',
  'publish_asset',
  'update_metadata',
]

export const EXECUTABLE_ACTION_TYPES = new Set([
  'run_planner',
  'queue_workflow',
  'start_runtime',
  'generate_asset',
  'generate_image',
  'generate_video',
])
