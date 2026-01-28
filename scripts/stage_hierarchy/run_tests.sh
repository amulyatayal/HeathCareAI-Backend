#!/bin/bash

# Run stage-related integration tests
echo "Running Stage Integration Tests..."

# Navigate to project root
cd "$(dirname "$0")/../.."
export PYTHONPATH=$PYTHONPATH:$(pwd)

# Run specific integration test
python3 -m unittest tests/integration/test_stage_personalization.py -v
