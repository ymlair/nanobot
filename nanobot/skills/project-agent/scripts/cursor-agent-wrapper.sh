#!/bin/bash
# cursor-agent wrapper script
# Usage: ./cursor-agent-wrapper.sh <prompt> [--project <name>] [--workspace <path>]

PROMPT="$1"
shift

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)
      WORKSPACE="$2"
      shift 2
      ;;
    --project)
      PROJECT_NAME="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done

# Get workspace from project name if not provided
if [[ -z "$WORKSPACE" && -n "$PROJECT_NAME" ]]; then
  if [[ -f "$HOME/.nanobot/projects.json" ]]; then
    WORKSPACE=$(jq -r ".\"$PROJECT_NAME\"" "$HOME/.nanobot/projects.json")
    if [[ "$WORKSPACE" == "null" ]]; then
      echo "Error: Project '$PROJECT_NAME' not found in ~/.nanobot/projects.json"
      exit 1
    fi
    echo "Found project '$PROJECT_NAME' at: $WORKSPACE"
  else
    echo "Error: Project configuration file ~/.nanobot/projects.json not found"
    exit 1
  fi
fi

# Build command
CMD="cursor-agent -p --force \"$PROMPT\""

if [[ -n "$WORKSPACE" ]]; then
  CMD="$CMD --workspace \"$WORKSPACE\""
fi

# Add branch creation instruction for code changes
if [[ "$PROMPT" == *"修改"* || "$PROMPT" == *"优化"* || "$PROMPT" == *"开发"* || "$PROMPT" == *"添加"* ]]; then
  CMD="$CMD --instruction '请先从主分支创建新的功能分支，命名格式为 feature/YYYYMMDD-功能描述，然后在新分支上进行代码修改'"
fi

# Execute command
echo "Executing: $CMD"
echo "-------------------"
eval "$CMD"