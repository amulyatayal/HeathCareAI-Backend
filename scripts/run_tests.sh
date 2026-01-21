#!/bin/bash

# Run all verification tests
echo "Running Integration Tests..."
export PYTHONPATH=$PYTHONPATH:$(pwd)

# Run specific integration test
python3 -m unittest tests/integration/test_stage_personalization.py -v
