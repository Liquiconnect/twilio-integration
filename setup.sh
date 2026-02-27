# setup.sh
#!/bin/bash

# Install pre-commit if not installed
if ! [ -x "$(command -v pre-commit)" ]; then
    echo "Pre-commit is not installed. Installing pre-commit..."
    pip install pre-commit
fi

# Install the pre-commit hook
pre-commit install
