# OpenRouter API key setup

1. Create a key at [OpenRouter API keys](https://openrouter.ai/settings/keys).
2. Add the following to the ignored `.env` in the **Windows worker checkout**, updating existing settings and preserving the desktop controller settings:

   ```dotenv
   OPENROUTER_API_KEY=your-key-here
   EAS_MODEL_PROVIDER=openrouter
   EAS_MODEL_ID=openai/gpt-5.6-luna
   ```

3. Set `EAS_MODEL_MODE=live` on both machines when ready to make API calls. Restart the backend with `enterprise serve` and restart the idle Windows `EAS-Worker` task. Keep the key only on the worker. Jobs that need assistance can then call GPT 5.6 Luna through OpenRouter.

The [LangChain OpenRouter integration](https://docs.langchain.com/oss/python/integrations/chat/openrouter) is included in the project dependencies. Adding a key alone does not switch out of simulated mode. The application consumes it through the environment; no key needs to appear in a conversation, screenshot, or source commit. Live calls are limited to 12 per job by default, with 2,048 output tokens per call, a 20-second request timeout, and no automatic provider retries. Assistant tools still require individual staff approval.

An ignored `.env` remains readable to tools with filesystem access. This project does not enforce an agent-specific read ban. Use a separate project key, restricted permissions where supported, usage monitoring, and key rotation.
