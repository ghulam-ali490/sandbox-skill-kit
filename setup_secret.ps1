$keys = @(
    'ANTHROPIC_WEBHOOK_SECRET=placeholder',
    'ANTHROPIC_ENVIRONMENT_ID=env_placeholder',
    'ANTHROPIC_ENVIRONMENT_KEY=sk-ant-oat-placeholder'
)
& modal secret create cma-self-hosted-sandboxes-secrets @keys
