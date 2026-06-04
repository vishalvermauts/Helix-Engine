FROM node:20-bullseye-slim

# Install system dependencies needed for common dev tools and headless browsers
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install global node packages for linting and formatting
RUN npm install -g eslint prettier

# Set up working directory inside the container
WORKDIR /workspace

# Container will run idle so we can exec into it
CMD ["tail", "-f", "/dev/null"]
