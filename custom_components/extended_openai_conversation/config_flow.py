"""Config flow for OpenAI Conversation integration."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractContextManager
import logging
import types
from typing import Any, override

from openai._exceptions import APIConnectionError, AuthenticationError
import probatio as vol
import yaml

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_API_KEY, CONF_NAME, CONF_TOKEN
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, UnknownImplementationError
from homeassistant.helpers.config_entry_oauth2_flow import (
    AbstractOAuth2FlowHandler,
    async_get_config_entry_implementation,
    async_get_implementations,
)
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    ObjectSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TemplateSelector,
)

from .application_credentials import oauth_application_context
from .const import (
    API_PROVIDERS,
    CONF_ADVANCED_OPTIONS,
    CONF_API_PROVIDER,
    CONF_API_VERSION,
    CONF_BASE_URL,
    CONF_CHAT_MODEL,
    CONF_CONTEXT_THRESHOLD,
    CONF_CONTEXT_TRUNCATE_STRATEGY,
    CONF_EXTRA_BODY,
    CONF_FUNCTION_TOOLS,
    CONF_MAX_FUNCTION_CALLS_PER_CONVERSATION,
    CONF_MAX_TOKENS,
    CONF_ORGANIZATION,
    CONF_PROMPT,
    CONF_REASONING_EFFORT,
    CONF_SERVICE_TIER,
    CONF_SERVICE_TYPE,
    CONF_SHORTEN_TOOL_CALL_ID,
    CONF_SKILLS,
    CONF_SKIP_AUTHENTICATION,
    CONF_TEMPERATURE,
    CONF_TOP_P,
    CONTEXT_TRUNCATE_STRATEGIES,
    DEFAULT_ADVANCED_OPTIONS,
    DEFAULT_AI_TASK_NAME,
    DEFAULT_AI_TASK_OPTIONS,
    DEFAULT_API_PROVIDER,
    DEFAULT_CHAT_MODEL,
    DEFAULT_CONF_BASE_URL,
    DEFAULT_CONF_FUNCTION_TOOLS,
    DEFAULT_CONTEXT_THRESHOLD,
    DEFAULT_CONTEXT_TRUNCATE_STRATEGY,
    DEFAULT_CONVERSATION_NAME,
    DEFAULT_EXTRA_BODY,
    DEFAULT_MAX_FUNCTION_CALLS_PER_CONVERSATION,
    DEFAULT_MAX_TOKENS,
    DEFAULT_NAME,
    DEFAULT_PROMPT,
    DEFAULT_REASONING_EFFORT,
    DEFAULT_SERVICE_TIER,
    DEFAULT_SHORTEN_TOOL_CALL_ID,
    DEFAULT_SKIP_AUTHENTICATION,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
    DOMAIN,
    REASONING_EFFORT_OPTIONS,
    SERVICE_TIER_OPTIONS,
    SERVICE_TYPE_AI_ENDPOINT,
    SERVICE_TYPE_MCP,
    SERVICE_TYPES,
)
from .helpers import get_authenticated_client, get_model_config, get_service_type
from .mcp_client import (
    CONF_MCP_AUTHORIZATION_URL,
    CONF_MCP_DESCRIPTION,
    CONF_MCP_DISABLED_TOOL_MODE,
    CONF_MCP_DISABLED_TOOLS,
    CONF_MCP_HEADERS,
    CONF_MCP_INCLUDE_PERMANENT_SCHEMAS,
    CONF_MCP_OAUTH_SCOPE,
    CONF_MCP_ON_DEMAND_DISCOVERY,
    CONF_MCP_PERFORM_TOOL_DISCOVERY,
    CONF_MCP_PERMANENT_TOOL_EXPOSURE,
    CONF_MCP_PERMANENT_TOOL_MODE,
    CONF_MCP_PERMANENT_TOOLS,
    CONF_MCP_PROVIDE_DEFAULT_PROMPT,
    CONF_MCP_REGEX_TIMEOUT,
    CONF_MCP_SERVER_ID,
    CONF_MCP_SERVER_URL,
    CONF_MCP_TOKEN_URL,
    CONF_MCP_TOOL_NAME_PATTERN,
    CONF_MCP_USE_OAUTH,
    DEFAULT_MCP_DISABLED_TOOL_MODE,
    DEFAULT_MCP_INCLUDE_PERMANENT_SCHEMAS,
    DEFAULT_MCP_ON_DEMAND_DISCOVERY,
    DEFAULT_MCP_PERFORM_TOOL_DISCOVERY,
    DEFAULT_MCP_PERMANENT_TOOL_EXPOSURE,
    DEFAULT_MCP_PERMANENT_TOOL_MODE,
    DEFAULT_MCP_PROVIDE_DEFAULT_PROMPT,
    DEFAULT_MCP_REGEX_TIMEOUT,
    DEFAULT_MCP_TOOL_NAME_PATTERN,
    MCP_TOOL_FILTER_SELECTED,
    MCP_TOOL_FILTER_UNSELECTED,
    MCPClientConfigFlow,
    MCPClientConfigFlowResult,
    MCPConfigError,
    MCPContextEstimate,
    MCPDiscoveryResult,
    MCPServerConfig,
    MCPServiceConfig,
    async_discover_mcp_oauth,
)
from .mcp_oauth import oauth_application_context_from_data, static_oauth_auth
from .skills import SkillManager

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SERVICE_TYPE): SelectSelector(
            SelectSelectorConfig(
                options=[item["key"] for item in SERVICE_TYPES],
                mode=SelectSelectorMode.DROPDOWN,
                translation_key="service_type",
            )
        )
    }
)

STEP_AI_ENDPOINT_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_NAME, default="ChatGPT"): str,
        vol.Required(CONF_API_KEY): str,
        vol.Optional(CONF_BASE_URL, default=DEFAULT_CONF_BASE_URL): str,
        vol.Optional(CONF_API_VERSION): str,
        vol.Optional(CONF_ORGANIZATION): str,
        vol.Optional(
            CONF_SKIP_AUTHENTICATION, default=DEFAULT_SKIP_AUTHENTICATION
        ): bool,
        vol.Optional(CONF_API_PROVIDER, default=DEFAULT_API_PROVIDER): SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(
                        value=api_provider["key"], label=api_provider["label"]
                    )
                    for api_provider in API_PROVIDERS
                ],
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
    }
)

DEFAULT_CONF_FUNCTION_TOOLS_STR = yaml.dump(
    DEFAULT_CONF_FUNCTION_TOOLS, sort_keys=False
)

DEFAULT_OPTIONS = types.MappingProxyType(
    {
        CONF_PROMPT: DEFAULT_PROMPT,
        CONF_CHAT_MODEL: DEFAULT_CHAT_MODEL,
        CONF_MAX_TOKENS: DEFAULT_MAX_TOKENS,
        CONF_MAX_FUNCTION_CALLS_PER_CONVERSATION: DEFAULT_MAX_FUNCTION_CALLS_PER_CONVERSATION,
        CONF_TOP_P: DEFAULT_TOP_P,
        CONF_TEMPERATURE: DEFAULT_TEMPERATURE,
        CONF_FUNCTION_TOOLS: DEFAULT_CONF_FUNCTION_TOOLS_STR,
        CONF_CONTEXT_THRESHOLD: DEFAULT_CONTEXT_THRESHOLD,
        CONF_CONTEXT_TRUNCATE_STRATEGY: DEFAULT_CONTEXT_TRUNCATE_STRATEGY,
        CONF_SHORTEN_TOOL_CALL_ID: DEFAULT_SHORTEN_TOOL_CALL_ID,
        CONF_ADVANCED_OPTIONS: DEFAULT_ADVANCED_OPTIONS,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    api_key = data[CONF_API_KEY]
    base_url = data.get(CONF_BASE_URL)
    api_version = data.get(CONF_API_VERSION)
    organization = data.get(CONF_ORGANIZATION)
    skip_authentication = data.get(CONF_SKIP_AUTHENTICATION, False)
    api_provider = data.get(CONF_API_PROVIDER)

    if base_url == DEFAULT_CONF_BASE_URL:
        # Do not set base_url if using OpenAI for case of OpenAI's base_url change
        base_url = None
        data.pop(CONF_BASE_URL)

    if api_provider == "azure" and not base_url:
        raise HomeAssistantError("Azure OpenAI requires a custom base URL.")

    await get_authenticated_client(
        hass=hass,
        api_key=api_key,
        base_url=base_url,
        api_version=api_version,
        organization=organization,
        api_provider=api_provider,
        skip_authentication=skip_authentication,
    )


class ExtendedOpenAIConversationConfigFlow(AbstractOAuth2FlowHandler, domain=DOMAIN):
    """Handle a config flow for OpenAI Conversation."""

    VERSION = 2
    DOMAIN = DOMAIN
    logger = _LOGGER

    def __init__(self) -> None:
        """Initialize the config flow."""
        super().__init__()
        self._mcp_config: MCPServerConfig | None = None
        self._mcp_discovery: MCPDiscoveryResult | None = None
        self._mcp_options: dict[str, Any] | None = None
        self._mcp_service_config: MCPServiceConfig | None = None
        self._mcp_oauth_data: dict[str, Any] | None = None
        self._mcp_oauth_authenticated: bool = False
        self._mcp_oauth_status: bool | None = None
        self._mcp_connection_status: bool | None = None
        self._mcp_discovery_status: bool | None = None
        self._selected_service_type: str | None = None
        self._ai_endpoint_data: dict[str, Any] | None = None
        self._draft_revision: int = 0
        self._reviewed_revision: int | None = None
        self._reconfigure_entry: ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the type of service to configure."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        if user_input[CONF_SERVICE_TYPE] == SERVICE_TYPE_MCP:
            self._selected_service_type = SERVICE_TYPE_MCP
            return await self.async_step_mcp()

        self._selected_service_type = SERVICE_TYPE_AI_ENDPOINT
        return await self.async_step_ai_endpoint()

    async def async_step_service_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the central service configuration workflow."""
        if self._selected_service_type is None:
            return await self.async_step_user()

        options: list[str] = []
        allow_type_switch = self._reconfigure_entry is None
        if self._selected_service_type == SERVICE_TYPE_MCP:
            if allow_type_switch:
                options.append("switch_to_ai_endpoint")
            options.append("mcp")
            if self._mcp_config is not None:
                if self._mcp_config.use_oauth:
                    options.append("mcp_authenticate")
                if not self._mcp_config.use_oauth or self._mcp_oauth_authenticated:
                    options.append("mcp_filter_tools")
        else:
            if allow_type_switch:
                options.append("switch_to_mcp")
            options.append("ai_endpoint")

        service_configuration = self._service_configuration()
        if service_configuration is not None:
            options.append("service_review")
        if (
            service_configuration is not None
            and self._reviewed_revision == self._draft_revision
        ):
            options.append("service_save")

        is_mcp = self._selected_service_type == SERVICE_TYPE_MCP
        configuration_valid = (
            self._mcp_config is not None
            if is_mcp
            else self._ai_endpoint_data is not None
        )
        connection_status = (
            self._mcp_connection_status
            if is_mcp
            else (True if configuration_valid else None)
        )
        oauth_status = (
            self._mcp_oauth_status
            if is_mcp and self._mcp_config is not None and self._mcp_config.use_oauth
            else None
        )
        settings_status = self._mcp_service_config is not None if is_mcp else None
        review_status = (
            self._reviewed_revision == self._draft_revision
            if service_configuration is not None
            else None
        )

        return self.async_show_menu(
            step_id="service_menu",
            menu_options=options,
            description_placeholders={
                "configuration_status": self._status_icon(configuration_valid),
                "connection_status": self._status_icon(connection_status),
                "oauth_status": self._status_icon(oauth_status),
                "settings_status": self._status_icon(settings_status),
                "review_status": self._status_icon(review_status),
            },
        )

    async def async_step_switch_to_ai_endpoint(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Switch this draft to an AI endpoint service."""
        self._select_service_type(SERVICE_TYPE_AI_ENDPOINT)
        return await self.async_step_ai_endpoint()

    async def async_step_switch_to_mcp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Switch this draft to an MCP service."""
        self._select_service_type(SERVICE_TYPE_MCP)
        return await self.async_step_mcp()

    async def async_step_ai_endpoint(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure an AI endpoint service."""

        errors = {}

        if user_input is not None:
            try:
                await validate_input(self.hass, user_input)
            except APIConnectionError:
                errors["base"] = "cannot_connect"
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                data = {**user_input, CONF_SERVICE_TYPE: SERVICE_TYPE_AI_ENDPOINT}
                if data != self._ai_endpoint_data:
                    self._ai_endpoint_data = data
                    self._mark_draft_changed()
                return await self.async_step_service_menu()

        schema = self.add_suggested_values_to_schema(
            STEP_AI_ENDPOINT_DATA_SCHEMA, self._ai_endpoint_data or {}
        )
        return self.async_show_form(
            step_id="ai_endpoint",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_mcp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure an MCP server and perform its requested initial check."""
        result: MCPClientConfigFlowResult = MCPClientConfigFlow(
            self._mcp_server_ids()
        ).process(user_input)

        if result.config is not None:
            assert user_input is not None
            previous_config = self._mcp_config
            if result.config != self._mcp_config:
                self._mcp_discovery = None
                self._mcp_options = None
                self._mcp_service_config = None
                self._mark_draft_changed()
            if self._oauth_connection_changed(previous_config, result.config):
                self._mcp_oauth_data = None
                self._mcp_oauth_authenticated = False
                self._mcp_oauth_status = None
            self._mcp_config = result.config
            self._mcp_options = {
                **(self._mcp_options or {}),
                CONF_MCP_PERFORM_TOOL_DISCOVERY: user_input.get(
                    CONF_MCP_PERFORM_TOOL_DISCOVERY,
                    DEFAULT_MCP_PERFORM_TOOL_DISCOVERY,
                ),
                CONF_MCP_PROVIDE_DEFAULT_PROMPT: user_input.get(
                    CONF_MCP_PROVIDE_DEFAULT_PROMPT,
                    DEFAULT_MCP_PROVIDE_DEFAULT_PROMPT,
                ),
                CONF_MCP_ON_DEMAND_DISCOVERY: user_input.get(
                    CONF_MCP_ON_DEMAND_DISCOVERY,
                    DEFAULT_MCP_ON_DEMAND_DISCOVERY,
                ),
            }
            if not self._mcp_options[CONF_MCP_PERFORM_TOOL_DISCOVERY]:
                self._mcp_discovery = None
                self._mcp_options.update(
                    {
                        CONF_MCP_PERMANENT_TOOLS: [],
                        CONF_MCP_INCLUDE_PERMANENT_SCHEMAS: False,
                        CONF_MCP_DISABLED_TOOLS: [],
                    }
                )
            if not self._mcp_options[CONF_MCP_ON_DEMAND_DISCOVERY]:
                self._mcp_options.update(
                    {
                        CONF_MCP_DISABLED_TOOL_MODE: DEFAULT_MCP_DISABLED_TOOL_MODE,
                        CONF_MCP_DISABLED_TOOLS: [],
                        CONF_MCP_TOOL_NAME_PATTERN: DEFAULT_MCP_TOOL_NAME_PATTERN,
                    }
                )
            if result.config.use_oauth and not self._mcp_oauth_authenticated:
                self._mcp_connection_status = None
                self._mcp_discovery_status = None
                self._set_mcp_service_config(self._mcp_policy_values())
            else:
                await self._async_test_mcp_server(run_requested_discovery=True)
                self._set_mcp_service_config(self._mcp_policy_values())
            return await self.async_step_service_menu()

        values = result.values
        if user_input is None and self._mcp_config is not None:
            values = {**self._mcp_config.to_dict(), **(self._mcp_options or {})}

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_NAME,
                    default=values[CONF_NAME],
                ): str,
                vol.Required(
                    CONF_MCP_SERVER_ID,
                    default=values[CONF_MCP_SERVER_ID],
                ): str,
                vol.Optional(
                    CONF_MCP_DESCRIPTION,
                    default=values.get(CONF_MCP_DESCRIPTION, ""),
                ): str,
                vol.Required(CONF_MCP_SERVER_URL): str,
                vol.Optional(
                    CONF_MCP_HEADERS,
                    default=values.get(CONF_MCP_HEADERS, {}),
                ): ObjectSelector(),
                vol.Required(
                    CONF_MCP_USE_OAUTH,
                    default=values.get(CONF_MCP_USE_OAUTH, False),
                ): BooleanSelector(),
                vol.Required(
                    CONF_MCP_PERFORM_TOOL_DISCOVERY,
                    default=values.get(
                        CONF_MCP_PERFORM_TOOL_DISCOVERY,
                        DEFAULT_MCP_PERFORM_TOOL_DISCOVERY,
                    ),
                ): BooleanSelector(),
                vol.Required(
                    CONF_MCP_PROVIDE_DEFAULT_PROMPT,
                    default=values.get(
                        CONF_MCP_PROVIDE_DEFAULT_PROMPT,
                        DEFAULT_MCP_PROVIDE_DEFAULT_PROMPT,
                    ),
                ): BooleanSelector(),
                vol.Required(
                    CONF_MCP_ON_DEMAND_DISCOVERY,
                    default=values.get(
                        CONF_MCP_ON_DEMAND_DISCOVERY,
                        DEFAULT_MCP_ON_DEMAND_DISCOVERY,
                    ),
                ): BooleanSelector(),
            }
        )
        schema = self.add_suggested_values_to_schema(schema, values)

        return self.async_show_form(
            step_id="mcp",
            data_schema=schema,
            errors=result.errors,
        )

    async def async_step_mcp_authenticate(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Discover OAuth endpoints and start Home Assistant's OAuth flow."""
        if self._mcp_config is None or not self._mcp_config.use_oauth:
            return self.async_abort(reason="mcp_invalid_flow_state")
        if user_input is None:
            return self.async_show_form(
                step_id="mcp_authenticate", data_schema=vol.Schema({})
            )
        try:
            oauth_config = await async_discover_mcp_oauth(self._mcp_config.url)
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unable to discover MCP OAuth metadata")
            self._mcp_oauth_status = False
            return await self.async_step_service_menu()

        self._mcp_oauth_data = {
            CONF_MCP_AUTHORIZATION_URL: oauth_config.authorization_url,
            CONF_MCP_TOKEN_URL: oauth_config.token_url,
            CONF_MCP_OAUTH_SCOPE: list(oauth_config.scopes),
            CONF_MCP_SERVER_URL: oauth_config.resource,
        }
        return await self.async_step_credentials_choice()

    async def async_step_credentials_choice(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose existing Application Credentials or add new credentials."""
        if self._mcp_oauth_data is None:
            return self.async_abort(reason="mcp_invalid_flow_state")
        with self._oauth_application_context():
            if not await async_get_implementations(self.hass, self.DOMAIN):
                return await self.async_step_new_credentials()
        return self.async_show_menu(
            step_id="credentials_choice",
            menu_options=["pick_implementation", "new_credentials"],
        )

    async def async_step_new_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Direct Home Assistant to collect Application Credentials."""
        return self.async_abort(reason="missing_credentials")

    @override
    async def async_step_pick_implementation(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Resolve credentials against the current MCP authorization server."""
        with self._oauth_application_context():
            return await super().async_step_pick_implementation(user_input)

    @property
    @override
    def extra_authorize_data(self) -> dict[str, str]:
        """Request the scopes advertised by the MCP authorization server."""
        data: dict[str, str] = {"access_type": "offline", "prompt": "consent"}
        if self._mcp_oauth_data is not None and (
            scopes := self._mcp_oauth_data.get(CONF_MCP_OAUTH_SCOPE)
        ):
            data["scope"] = " ".join(scopes)
        return {**data, **super().extra_authorize_data}

    @override
    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Retain HA-managed OAuth data, then return to the service workflow."""
        if self._mcp_oauth_data is None:
            return self.async_abort(reason="mcp_invalid_flow_state")
        oauth_data = {**self._mcp_oauth_data, **data}

        if self.source == SOURCE_REAUTH:
            entry = self._get_reauth_entry()
            return self.async_update_reload_and_abort(
                entry,
                data={**entry.data, **oauth_data},
            )

        self._mcp_oauth_data = oauth_data
        self._mcp_oauth_authenticated = True
        self._mcp_oauth_status = True
        self._mark_draft_changed()
        await self._async_test_mcp_server(run_requested_discovery=True)
        self._set_mcp_service_config(self._mcp_policy_values())
        return await self.async_step_service_menu()

    @override
    async def async_step_creation(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Return failed OAuth token exchanges to the retained MCP draft."""
        result = await super().async_step_creation(user_input)
        if result["type"] == FlowResultType.ABORT:
            self._mcp_oauth_authenticated = False
            self._mcp_oauth_status = False
            return await self.async_step_service_menu()
        return result

    @override
    async def async_step_authorize_rejected(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Return a rejected OAuth authorization to the retained MCP draft."""
        self._mcp_oauth_authenticated = False
        self._mcp_oauth_status = False
        return await self.async_step_service_menu()

    async def async_step_mcp_filter_tools(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure permanent exposure and hard tool-access filters."""
        if self._mcp_config is None:
            return self.async_abort(reason="mcp_invalid_flow_state")
        if self._mcp_config.use_oauth and not self._mcp_oauth_authenticated:
            return await self.async_step_service_menu()

        errors: dict[str, str] = {}
        if user_input is not None:
            options = {**self._mcp_policy_values(), **user_input}
            previous_config = self._mcp_service_config
            errors = self._set_mcp_service_config(options)
            if not errors:
                if self._mcp_service_config != previous_config:
                    self._mark_draft_changed()
                return await self.async_step_service_menu()

        values = self._mcp_policy_values()
        schema_fields: dict[Any, Any] = {}
        discovery = self._mcp_discovery
        if values[CONF_MCP_PERFORM_TOOL_DISCOVERY] and discovery is not None:
            tool_options = [
                SelectOptionDict(value=tool.name, label=tool.title or tool.name)
                for tool in discovery.tools
            ]
            mode_options = [MCP_TOOL_FILTER_SELECTED, MCP_TOOL_FILTER_UNSELECTED]
            schema_fields.update(
                {
                    vol.Required(
                        CONF_MCP_PERMANENT_TOOL_MODE,
                        default=values[CONF_MCP_PERMANENT_TOOL_MODE],
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=mode_options,
                            mode=SelectSelectorMode.DROPDOWN,
                            translation_key="mcp_tool_filter_mode",
                        )
                    ),
                    vol.Optional(
                        CONF_MCP_PERMANENT_TOOLS,
                        default=values[CONF_MCP_PERMANENT_TOOLS],
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=tool_options,
                            multiple=True,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        CONF_MCP_INCLUDE_PERMANENT_SCHEMAS,
                        default=values[CONF_MCP_INCLUDE_PERMANENT_SCHEMAS],
                    ): BooleanSelector(),
                }
            )
        if values[CONF_MCP_ON_DEMAND_DISCOVERY] and discovery is not None:
            schema_fields.update(
                {
                    vol.Required(
                        CONF_MCP_DISABLED_TOOL_MODE,
                        default=values[CONF_MCP_DISABLED_TOOL_MODE],
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=mode_options,
                            mode=SelectSelectorMode.DROPDOWN,
                            translation_key="mcp_tool_filter_mode",
                        )
                    ),
                    vol.Optional(
                        CONF_MCP_DISABLED_TOOLS,
                        default=values[CONF_MCP_DISABLED_TOOLS],
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=tool_options,
                            multiple=True,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            )
        if values[CONF_MCP_ON_DEMAND_DISCOVERY]:
            schema_fields.update(
                {
                    vol.Optional(
                        CONF_MCP_TOOL_NAME_PATTERN,
                        default=values[CONF_MCP_TOOL_NAME_PATTERN],
                    ): str,
                    vol.Required(
                        CONF_MCP_REGEX_TIMEOUT,
                        default=values[CONF_MCP_REGEX_TIMEOUT],
                    ): NumberSelector(NumberSelectorConfig(min=0.01, step=0.01)),
                }
            )

        return self.async_show_form(
            step_id="mcp_filter_tools",
            data_schema=vol.Schema(schema_fields),
            description_placeholders={
                "tool_count": str(
                    len(self._mcp_discovery.tools) if self._mcp_discovery else 0
                )
            },
            errors=errors,
        )

    async def _async_test_mcp_server(self, *, run_requested_discovery: bool) -> None:
        """Run exactly one requested connection operation and retain its status."""
        if self._mcp_config is None:
            return
        processor = MCPClientConfigFlow(self._mcp_server_ids())
        auth = self._mcp_oauth_auth() if self._mcp_config.use_oauth else None
        discover = bool(
            (self._mcp_options or {}).get(
                CONF_MCP_PERFORM_TOOL_DISCOVERY,
                DEFAULT_MCP_PERFORM_TOOL_DISCOVERY,
            )
        )
        if not discover:
            self._mcp_discovery_status = None
        try:
            if run_requested_discovery and discover:
                self._mcp_discovery = await processor.discover(
                    self._mcp_config, auth=auth
                )
                self._mcp_connection_status = True
                self._mcp_discovery_status = True
            else:
                await processor.check_connection(self._mcp_config, auth=auth)
                self._mcp_connection_status = True
                if not discover:
                    self._mcp_discovery_status = None
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unable to connect to the MCP server")
            self._mcp_connection_status = False
            if run_requested_discovery and discover:
                self._mcp_discovery = None
                self._mcp_discovery_status = False

    def _mcp_policy_values(self) -> dict[str, Any]:
        """Return complete policy values using the current draft and defaults."""
        return {
            CONF_MCP_PERFORM_TOOL_DISCOVERY: DEFAULT_MCP_PERFORM_TOOL_DISCOVERY,
            CONF_MCP_PROVIDE_DEFAULT_PROMPT: DEFAULT_MCP_PROVIDE_DEFAULT_PROMPT,
            CONF_MCP_PERMANENT_TOOL_MODE: DEFAULT_MCP_PERMANENT_TOOL_MODE,
            CONF_MCP_PERMANENT_TOOLS: [],
            CONF_MCP_INCLUDE_PERMANENT_SCHEMAS: DEFAULT_MCP_INCLUDE_PERMANENT_SCHEMAS,
            CONF_MCP_ON_DEMAND_DISCOVERY: DEFAULT_MCP_ON_DEMAND_DISCOVERY,
            CONF_MCP_DISABLED_TOOL_MODE: DEFAULT_MCP_DISABLED_TOOL_MODE,
            CONF_MCP_DISABLED_TOOLS: [],
            CONF_MCP_TOOL_NAME_PATTERN: DEFAULT_MCP_TOOL_NAME_PATTERN,
            CONF_MCP_REGEX_TIMEOUT: DEFAULT_MCP_REGEX_TIMEOUT,
            **(self._mcp_options or {}),
        }

    async def async_step_mcp_ask_discovery(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose whether to discover the server's tools."""
        if self._mcp_config is None:
            return self.async_abort(reason="mcp_invalid_flow_state")

        return await self.async_step_service_menu()

    async def async_step_mcp_perform_discovery(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Discover the server's tools after the user explicitly requests it."""
        if self._mcp_config is None:
            return self.async_abort(reason="mcp_invalid_flow_state")

        processor: MCPClientConfigFlow = MCPClientConfigFlow(self._mcp_server_ids())
        try:
            if self._mcp_config.use_oauth:
                self._mcp_discovery = await processor.discover(
                    self._mcp_config, auth=self._mcp_oauth_auth()
                )
            else:
                self._mcp_discovery = await processor.discover(self._mcp_config)
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected error during MCP tool discovery")
            self._mcp_connection_status = False
            self._mcp_discovery_status = False
            return await self.async_step_service_menu()
        else:
            # restore the previous options
            previous_options: dict[str, Any] | None = self._mcp_options
            if previous_options is not None:
                available_tools: set[str] = {
                    tool.name for tool in self._mcp_discovery.tools
                }
                previous_options = {
                    **previous_options,
                    CONF_MCP_PERMANENT_TOOLS: [
                        name
                        for name in previous_options.get(CONF_MCP_PERMANENT_TOOLS, [])
                        if name in available_tools
                    ],
                }

            self._mcp_service_config = None
            self._mcp_options = previous_options
            self._mark_draft_changed()
            return await self.async_step_mcp_tools()

    async def async_step_mcp_skip_discovery(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Continue setup without discovering tools."""
        if self._mcp_config is None:
            return self.async_abort(reason="mcp_invalid_flow_state")

        self._mcp_discovery = None
        return await self.async_step_mcp_options()

    async def async_step_mcp_tools(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure tool exposure from the discovered MCP catalogue."""
        if self._mcp_discovery is None:
            return self.async_abort(reason="mcp_invalid_flow_state")

        errors: dict[str, str] = {}
        if user_input is not None:
            previous_config = self._mcp_service_config
            options = {
                CONF_MCP_PERMANENT_TOOL_EXPOSURE: DEFAULT_MCP_PERMANENT_TOOL_EXPOSURE,
                CONF_MCP_PERMANENT_TOOLS: [],
                CONF_MCP_INCLUDE_PERMANENT_SCHEMAS: DEFAULT_MCP_INCLUDE_PERMANENT_SCHEMAS,
                CONF_MCP_ON_DEMAND_DISCOVERY: DEFAULT_MCP_ON_DEMAND_DISCOVERY,
                CONF_MCP_REGEX_TIMEOUT: DEFAULT_MCP_REGEX_TIMEOUT,
                **user_input,
            }
            errors = self._set_mcp_service_config(options)
            if not errors:
                if self._mcp_service_config != previous_config:
                    self._mark_draft_changed()
                return await self.async_step_service_menu()

        values = self._mcp_options or {}
        tool_options = [
            SelectOptionDict(value=tool.name, label=tool.title or tool.name)
            for tool in self._mcp_discovery.tools
        ]
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MCP_PERMANENT_TOOL_EXPOSURE,
                    default=values.get(
                        CONF_MCP_PERMANENT_TOOL_EXPOSURE,
                        DEFAULT_MCP_PERMANENT_TOOL_EXPOSURE,
                    ),
                ): BooleanSelector(),
                vol.Optional(
                    CONF_MCP_PERMANENT_TOOLS,
                    default=values.get(CONF_MCP_PERMANENT_TOOLS, []),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=tool_options,
                        multiple=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_MCP_INCLUDE_PERMANENT_SCHEMAS,
                    default=values.get(
                        CONF_MCP_INCLUDE_PERMANENT_SCHEMAS,
                        DEFAULT_MCP_INCLUDE_PERMANENT_SCHEMAS,
                    ),
                ): BooleanSelector(),
                vol.Required(
                    CONF_MCP_ON_DEMAND_DISCOVERY,
                    default=values.get(
                        CONF_MCP_ON_DEMAND_DISCOVERY,
                        DEFAULT_MCP_ON_DEMAND_DISCOVERY,
                    ),
                ): BooleanSelector(),
                vol.Required(
                    CONF_MCP_REGEX_TIMEOUT,
                    default=values.get(
                        CONF_MCP_REGEX_TIMEOUT,
                        DEFAULT_MCP_REGEX_TIMEOUT,
                    ),
                ): NumberSelector(NumberSelectorConfig(min=0.01, step=0.01)),
            }
        )

        return self.async_show_form(
            step_id="mcp_tools",
            data_schema=schema,
            description_placeholders={
                "server_name": self._mcp_discovery.server.name,
                "tool_count": str(len(self._mcp_discovery.tools)),
            },
            errors=errors,
        )

    async def async_step_mcp_options(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure MCP policies when initial tool discovery was skipped."""
        if self._mcp_config is None:
            return self.async_abort(reason="mcp_invalid_flow_state")

        errors: dict[str, str] = {}
        if user_input is not None:
            previous_config = self._mcp_service_config
            options = {
                CONF_MCP_PERMANENT_TOOL_EXPOSURE: False,
                CONF_MCP_PERMANENT_TOOLS: [],
                CONF_MCP_INCLUDE_PERMANENT_SCHEMAS: False,
                **user_input,
            }
            errors = self._set_mcp_service_config(options)
            if not errors:
                if self._mcp_service_config != previous_config:
                    self._mark_draft_changed()
                self._mcp_discovery_status = None
                return await self.async_step_service_menu()

        values = self._mcp_options or {}
        return self.async_show_form(
            step_id="mcp_options",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MCP_ON_DEMAND_DISCOVERY,
                        default=values.get(
                            CONF_MCP_ON_DEMAND_DISCOVERY,
                            DEFAULT_MCP_ON_DEMAND_DISCOVERY,
                        ),
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_MCP_REGEX_TIMEOUT,
                        default=values.get(
                            CONF_MCP_REGEX_TIMEOUT,
                            DEFAULT_MCP_REGEX_TIMEOUT,
                        ),
                    ): NumberSelector(NumberSelectorConfig(min=0.01, step=0.01)),
                }
            ),
            errors=errors,
        )

    def _set_mcp_service_config(self, options: dict[str, Any]) -> dict[str, str]:
        """Validate MCP policies and retain their normalized service config."""
        if self._mcp_config is None:
            return {"base": "mcp_invalid_flow_state"}

        try:
            service_config = MCPServiceConfig.from_selection(
                self._mcp_config,
                self._mcp_discovery,
                perform_tool_discovery=options[CONF_MCP_PERFORM_TOOL_DISCOVERY],
                provide_default_prompt=options[CONF_MCP_PROVIDE_DEFAULT_PROMPT],
                permanent_tool_mode=options[CONF_MCP_PERMANENT_TOOL_MODE],
                selected_tool_names=options[CONF_MCP_PERMANENT_TOOLS],
                include_permanent_schemas=options[CONF_MCP_INCLUDE_PERMANENT_SCHEMAS],
                on_demand_discovery=options[CONF_MCP_ON_DEMAND_DISCOVERY],
                disabled_tool_mode=options[CONF_MCP_DISABLED_TOOL_MODE],
                disabled_tool_names=options[CONF_MCP_DISABLED_TOOLS],
                tool_name_pattern=options[CONF_MCP_TOOL_NAME_PATTERN],
                regex_timeout=options[CONF_MCP_REGEX_TIMEOUT],
            )
        except MCPConfigError as err:
            self._mcp_options = options
            self._mcp_service_config = None
            return {err.field: err.code}

        self._mcp_service_config = service_config
        self._mcp_options = {
            CONF_MCP_PERFORM_TOOL_DISCOVERY: service_config.perform_tool_discovery,
            CONF_MCP_PROVIDE_DEFAULT_PROMPT: service_config.provide_default_prompt,
            CONF_MCP_PERMANENT_TOOL_MODE: service_config.permanent_tool_mode,
            CONF_MCP_PERMANENT_TOOLS: list(service_config.permanent_tool_selection),
            CONF_MCP_INCLUDE_PERMANENT_SCHEMAS: (
                service_config.include_permanent_schemas
            ),
            CONF_MCP_ON_DEMAND_DISCOVERY: service_config.on_demand_discovery,
            CONF_MCP_DISABLED_TOOL_MODE: service_config.disabled_tool_mode,
            CONF_MCP_DISABLED_TOOLS: list(service_config.disabled_tools),
            CONF_MCP_TOOL_NAME_PATTERN: service_config.tool_name_pattern,
            CONF_MCP_REGEX_TIMEOUT: service_config.regex_timeout,
        }
        return {}

    async def async_step_mcp_review(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Review MCP policy and estimated permanent context size."""
        if self._mcp_config is None:
            return self.async_abort(reason="mcp_invalid_flow_state")

        service_config: MCPServiceConfig | None = self._mcp_service_config
        if service_config is None:
            return self.async_abort(reason="mcp_invalid_flow_state")

        if user_input is not None:
            self._reviewed_revision = self._draft_revision
            return await self.async_step_service_menu()

        if service_config.server.use_oauth and not self._mcp_oauth_authenticated:
            self._mcp_connection_status = None
        else:
            await self._async_test_mcp_server(run_requested_discovery=False)

        estimate: MCPContextEstimate = MCPContextEstimate.estimate_permanent_context(
            service_config.server,
            service_config.permanent_tools,
            include_schemas=service_config.include_permanent_schemas,
            include_default_prompt=service_config.provide_default_prompt,
        )

        return self.async_show_form(
            step_id="mcp_review",
            data_schema=vol.Schema({}),
            description_placeholders={
                "permanent_tools_selected": self._status_icon(
                    service_config.permanent_tool_mode == MCP_TOOL_FILTER_SELECTED
                ),
                "selected_tool_count": str(estimate.selected_tool_count),
                "schemas_included": self._status_icon(
                    bool(
                        service_config.include_permanent_schemas
                        and estimate.selected_tool_count
                    )
                ),
                "on_demand_discovery": self._status_icon(
                    service_config.on_demand_discovery
                ),
                "default_prompt": self._status_icon(
                    service_config.provide_default_prompt
                ),
                "disabled_tools_selected": self._status_icon(
                    service_config.disabled_tool_mode == MCP_TOOL_FILTER_SELECTED
                ),
                "disabled_tool_count": str(len(service_config.disabled_tools)),
                "tool_name_pattern": service_config.tool_name_pattern or "—",
                "connection_status": self._status_icon(self._mcp_connection_status),
                "discovery_status": self._status_icon(self._mcp_discovery_status),
                "discovered_tool_count": str(
                    len(self._mcp_discovery.tools) if self._mcp_discovery else 0
                ),
                "regex_timeout": str(service_config.regex_timeout),
                "character_count": str(estimate.character_count),
                "byte_count": str(estimate.byte_count),
                "estimated_tokens": str(estimate.estimated_tokens),
            },
        )

    async def async_step_service_review(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Review the currently selected service configuration."""
        if self._selected_service_type == SERVICE_TYPE_MCP:
            return await self.async_step_mcp_review(user_input)
        if self._ai_endpoint_data is None:
            return await self.async_step_service_menu()
        if user_input is not None:
            self._reviewed_revision = self._draft_revision
            return await self.async_step_service_menu()
        return self.async_show_form(
            step_id="ai_endpoint_review",
            data_schema=vol.Schema({}),
            description_placeholders={
                "name": str(self._ai_endpoint_data.get(CONF_NAME, DEFAULT_NAME)),
                "base_url": str(
                    self._ai_endpoint_data.get(CONF_BASE_URL, DEFAULT_CONF_BASE_URL)
                ),
            },
        )

    async def async_step_ai_endpoint_review(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the AI endpoint review form's submitted step ID."""
        return await self.async_step_service_review(user_input)

    async def async_step_service_save(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Persist a locally validated and reviewed service configuration."""
        data = self._service_configuration()
        if data is None or self._reviewed_revision != self._draft_revision:
            return await self.async_step_service_menu()

        title = str(data.get(CONF_NAME, DEFAULT_NAME))
        if self._reconfigure_entry is not None:
            return self.async_update_reload_and_abort(
                self._reconfigure_entry, title=title, data=data
            )
        if self._selected_service_type == SERVICE_TYPE_MCP:
            return self.async_create_entry(title=title, data=data)
        return self.async_create_entry(
            title=title,
            data=data,
            subentries=[
                {
                    "subentry_type": "conversation",
                    "data": dict(DEFAULT_OPTIONS),
                    "title": DEFAULT_CONVERSATION_NAME,
                    "unique_id": None,
                },
                {
                    "subentry_type": "ai_task_data",
                    "data": dict(DEFAULT_AI_TASK_OPTIONS),
                    "title": DEFAULT_AI_TASK_NAME,
                    "unique_id": None,
                },
            ],
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start Home Assistant's standard OAuth reauthentication flow."""
        entry = self._get_reauth_entry()
        service_config = MCPServiceConfig.from_dict(entry.data)
        self._selected_service_type = SERVICE_TYPE_MCP
        self._mcp_config = service_config.server
        self._mcp_oauth_data = dict(entry.data)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: Mapping[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm and launch OAuth reauthentication."""
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        entry = self._get_reauth_entry()
        try:
            with self._oauth_application_context():
                self.flow_impl = await async_get_config_entry_implementation(
                    self.hass, entry
                )
        except UnknownImplementationError:
            return await self.async_step_mcp_authenticate()
        return await self.async_step_auth()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure an existing service through the shared workflow menu."""
        entry = self._get_reconfigure_entry()
        self._reconfigure_entry = entry
        self._selected_service_type = get_service_type(entry)
        if self._selected_service_type == SERVICE_TYPE_MCP:
            service_config = MCPServiceConfig.from_dict(entry.data)
            self._mcp_config = service_config.server
            self._mcp_discovery = None
            self._mcp_options = {
                CONF_MCP_PERFORM_TOOL_DISCOVERY: service_config.perform_tool_discovery,
                CONF_MCP_PROVIDE_DEFAULT_PROMPT: service_config.provide_default_prompt,
                CONF_MCP_PERMANENT_TOOL_MODE: service_config.permanent_tool_mode,
                CONF_MCP_PERMANENT_TOOLS: list(service_config.permanent_tool_selection),
                CONF_MCP_INCLUDE_PERMANENT_SCHEMAS: service_config.include_permanent_schemas,
                CONF_MCP_ON_DEMAND_DISCOVERY: service_config.on_demand_discovery,
                CONF_MCP_DISABLED_TOOL_MODE: service_config.disabled_tool_mode,
                CONF_MCP_DISABLED_TOOLS: list(service_config.disabled_tools),
                CONF_MCP_TOOL_NAME_PATTERN: service_config.tool_name_pattern,
                CONF_MCP_REGEX_TIMEOUT: service_config.regex_timeout,
            }
            self._mcp_service_config = service_config
            if service_config.server.use_oauth:
                self._mcp_oauth_data = {
                    key: entry.data[key]
                    for key in (
                        CONF_MCP_AUTHORIZATION_URL,
                        CONF_MCP_TOKEN_URL,
                        CONF_MCP_OAUTH_SCOPE,
                        "auth_implementation",
                        CONF_TOKEN,
                    )
                    if key in entry.data
                }
                self._mcp_oauth_authenticated = CONF_TOKEN in self._mcp_oauth_data
                self._mcp_oauth_status = True if self._mcp_oauth_authenticated else None
        else:
            self._ai_endpoint_data = dict(entry.data)
        self._draft_revision = 1
        self._reviewed_revision = None
        return await self.async_step_service_menu()

    def _select_service_type(self, service_type: str) -> None:
        """Select a draft type and invalidate its previous review."""
        if service_type != self._selected_service_type:
            self._selected_service_type = service_type
            self._mark_draft_changed()

    def _mark_draft_changed(self) -> None:
        """Invalidate review whenever meaningful draft state changes."""
        self._draft_revision += 1
        self._reviewed_revision = None

    @staticmethod
    def _status_icon(status: bool | None) -> str:
        """Return a locale-neutral status marker for translated descriptions."""
        if status is None:
            return "—"
        return "✅" if status else "❌"

    def _service_configuration(self) -> dict[str, Any] | None:
        """Return the current valid service mapping without remote calls."""
        if self._selected_service_type == SERVICE_TYPE_AI_ENDPOINT:
            return self._ai_endpoint_data
        service_config = self._mcp_service_config
        if service_config is None:
            return None
        data = {**service_config.to_dict(), CONF_SERVICE_TYPE: SERVICE_TYPE_MCP}
        if service_config.server.use_oauth and self._mcp_oauth_data is not None:
            data.update(self._mcp_oauth_data)
        return data

    def _mcp_oauth_auth(self) -> Any:
        """Return static bearer authentication for config-flow MCP requests."""
        if self._mcp_oauth_data is None or CONF_TOKEN not in self._mcp_oauth_data:
            raise HomeAssistantError("MCP OAuth authentication has not completed")
        return static_oauth_auth(self._mcp_oauth_data)

    def _oauth_application_context(self) -> AbstractContextManager[None]:
        """Activate the current server for Home Assistant Application Credentials."""
        if self._mcp_oauth_data is None:
            raise HomeAssistantError("MCP OAuth metadata has not been discovered")
        return oauth_application_context(
            oauth_application_context_from_data(self._mcp_oauth_data)
        )

    @staticmethod
    def _oauth_connection_changed(
        previous: MCPServerConfig | None, current: MCPServerConfig
    ) -> bool:
        """Return whether existing OAuth credentials are no longer reusable."""
        if previous is None:
            return current.use_oauth
        return (
            previous.server_id,
            previous.url,
            previous.use_oauth,
        ) != (current.server_id, current.url, current.use_oauth)

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentries supported by this integration."""
        if get_service_type(config_entry) == SERVICE_TYPE_MCP:
            return {}
        return {
            "conversation": ExtendedOpenAISubentryFlowHandler,
            "ai_task_data": ExtendedOpenAIAITaskSubentryFlowHandler,
        }

    def _mcp_server_ids(self) -> set[str]:
        """Return the MCP server IDs reserved by Home Assistant entries."""
        return {
            entry.data[CONF_MCP_SERVER_ID]
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if (
                self._reconfigure_entry is None
                or entry.entry_id != self._reconfigure_entry.entry_id
            )
            and get_service_type(entry) == SERVICE_TYPE_MCP
            and CONF_MCP_SERVER_ID in entry.data
        }


class ExtendedOpenAISubentryFlowHandler(ConfigSubentryFlow):
    """Flow for managing OpenAI subentries."""

    options: dict[str, Any]
    _temp_data: dict[str, Any] | None = None
    _available_skills: list[dict[str, Any]] | None = None

    @property
    def _is_new(self) -> bool:
        """Return if this is a new subentry."""
        return bool(self.source == "user")

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a subentry."""
        self.options = dict(DEFAULT_OPTIONS)
        return await self.async_step_init()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration of a subentry."""
        self.options = dict(self._get_reconfigure_subentry().data)
        return await self.async_step_init()

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Manage the options."""
        # abort if entry is not loaded
        if self._get_entry().state != ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")

        # Load available skills
        if self._available_skills is None:
            self._available_skills = await self._async_get_skills()

        if user_input is not None:
            # Check if advanced options is enabled
            if user_input.get(CONF_ADVANCED_OPTIONS, False):
                # Store data and move to advanced step
                self._temp_data = user_input
                return await self.async_step_advanced()

            # No advanced options, save directly
            if self._is_new:
                title = user_input.get(CONF_NAME, DEFAULT_NAME)
                if CONF_NAME in user_input:
                    del user_input[CONF_NAME]
                return self.async_create_entry(
                    title=title,
                    data=user_input,
                )
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                data=user_input,
            )

        schema = self.openai_config_option_schema(self.options, self._available_skills)

        if self._is_new:
            schema = {
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                **schema,
            }

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(schema), self.options
            ),
        )

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle advanced options step."""
        if user_input is not None:
            # Merge advanced options with temp data
            final_data = {**(self._temp_data or {}), **user_input}

            if self._is_new:
                title = final_data.get(CONF_NAME, DEFAULT_NAME)
                final_data.pop(CONF_NAME, None)
                return self.async_create_entry(
                    title=title,
                    data=final_data,
                )
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                data=final_data,
            )

        # Build schema for advanced options based on selected model
        chat_model = (self._temp_data or {}).get(CONF_CHAT_MODEL, DEFAULT_CHAT_MODEL)
        model_config = get_model_config(
            chat_model, self._get_entry().data.get(CONF_BASE_URL)
        )

        schema: dict[Any, Any] = {}

        # Add top_p if supported
        if model_config["supports_top_p"]:
            schema[
                vol.Optional(
                    CONF_TOP_P,
                    default=DEFAULT_TOP_P,
                )
            ] = NumberSelector(NumberSelectorConfig(min=0, max=1, step=0.05))

        # Add temperature if supported
        if model_config["supports_temperature"]:
            schema[
                vol.Optional(
                    CONF_TEMPERATURE,
                    default=DEFAULT_TEMPERATURE,
                )
            ] = NumberSelector(NumberSelectorConfig(min=0, max=2, step=0.05))

        # Add reasoning_effort if supported (o1, o3, o4, gpt-5 models)
        if model_config.get("supports_reasoning_effort"):
            schema[
                vol.Optional(
                    CONF_REASONING_EFFORT,
                    default=DEFAULT_REASONING_EFFORT,
                )
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=opt, label=opt.capitalize())
                        for opt in REASONING_EFFORT_OPTIONS
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )

        # Add service_tier if supported (o3, o4, gpt-5 models)
        if model_config.get("supports_service_tier"):
            schema[
                vol.Optional(
                    CONF_SERVICE_TIER,
                    default=DEFAULT_SERVICE_TIER,
                )
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=opt, label=opt.capitalize())
                        for opt in SERVICE_TIER_OPTIONS
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )

        # Add extra_body - passthrough for OpenAI-compatible backends
        # (ollama, llama.cpp, vLLM, LM Studio). Accepts a Jinja-templatable
        # JSON string; empty disables.
        schema[
            vol.Optional(
                CONF_EXTRA_BODY,
                default=DEFAULT_EXTRA_BODY,
            )
        ] = TemplateSelector()

        # Add shorten_tool_call_id option (for Mistral AI compatibility)
        schema[
            vol.Optional(
                CONF_SHORTEN_TOOL_CALL_ID,
                default=DEFAULT_SHORTEN_TOOL_CALL_ID,
            )
        ] = BooleanSelector()

        return self.async_show_form(
            step_id="advanced",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(schema), self.options
            ),
        )

    async def _async_get_skills(self) -> list[dict[str, Any]]:
        """Load available skills using SkillManager."""
        skill_manager = await SkillManager.async_get_instance(self.hass)
        return [
            {
                "name": skill.name,
                "description": skill.description,
            }
            for skill in skill_manager.get_all_skills()
        ]

    def openai_config_option_schema(
        self, options: dict[str, Any], skills: list[dict[str, Any]] | None = None
    ) -> dict:
        """Return a schema for OpenAI completion options."""
        # If creating a new subentry and no skills in options, default to all loaded skills
        default_skills: list[str] = []
        if self._is_new and CONF_SKILLS not in options and skills:
            default_skills = [skill["name"] for skill in skills]

        current_skills = options.get(CONF_SKILLS, default_skills)

        schema: dict = {
            vol.Optional(
                CONF_PROMPT,
                default=DEFAULT_PROMPT,
            ): TemplateSelector(),
            vol.Optional(
                CONF_CHAT_MODEL,
                default=DEFAULT_CHAT_MODEL,
            ): str,
            vol.Optional(
                CONF_MAX_TOKENS,
                default=DEFAULT_MAX_TOKENS,
            ): int,
            vol.Optional(
                CONF_MAX_FUNCTION_CALLS_PER_CONVERSATION,
                default=DEFAULT_MAX_FUNCTION_CALLS_PER_CONVERSATION,
            ): int,
            vol.Optional(CONF_SKILLS, default=current_skills): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(
                            value=skill["name"],
                            label=skill["name"],
                        )
                        for skill in (skills or [])
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                    multiple=True,
                )
            ),
            vol.Optional(
                CONF_FUNCTION_TOOLS,
                default=DEFAULT_CONF_FUNCTION_TOOLS_STR,
            ): TemplateSelector(),
            vol.Optional(
                CONF_CONTEXT_THRESHOLD,
                default=DEFAULT_CONTEXT_THRESHOLD,
            ): int,
            vol.Optional(
                CONF_CONTEXT_TRUNCATE_STRATEGY,
                default=DEFAULT_CONTEXT_TRUNCATE_STRATEGY,
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=strategy["key"], label=strategy["label"])
                        for strategy in CONTEXT_TRUNCATE_STRATEGIES
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_ADVANCED_OPTIONS,
                default=DEFAULT_ADVANCED_OPTIONS,
            ): BooleanSelector(),
        }

        # Remove skills field if no skills available
        if not skills:
            schema = {
                key: value
                for key, value in schema.items()
                if not (isinstance(key, vol.Optional) and key.schema == CONF_SKILLS)
            }

        return schema


class ExtendedOpenAIAITaskSubentryFlowHandler(ConfigSubentryFlow):
    """Flow for managing AI Task subentries."""

    options: dict[str, Any]
    _temp_data: dict[str, Any] | None = None

    @property
    def _is_new(self) -> bool:
        """Return if this is a new subentry."""
        return bool(self.source == "user")

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a subentry."""
        self.options = dict(DEFAULT_AI_TASK_OPTIONS)
        return await self.async_step_init()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration of a subentry."""
        self.options = dict(self._get_reconfigure_subentry().data)
        return await self.async_step_init()

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Manage the options."""
        # Abort if entry is not loaded
        if self._get_entry().state != ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")

        if user_input is not None:
            # Check if advanced options is enabled
            if user_input.get(CONF_ADVANCED_OPTIONS, False):
                # Store data and move to advanced step
                self._temp_data = user_input
                return await self.async_step_advanced()

            # No advanced options, save directly
            if self._is_new:
                title = user_input.get(CONF_NAME, DEFAULT_AI_TASK_NAME)
                if CONF_NAME in user_input:
                    del user_input[CONF_NAME]
                return self.async_create_entry(
                    title=title,
                    data=user_input,
                )
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                data=user_input,
            )

        schema: dict = {}

        if self._is_new:
            schema[vol.Optional(CONF_NAME, default=DEFAULT_AI_TASK_NAME)] = str

        schema.update(
            {
                vol.Optional(
                    CONF_CHAT_MODEL,
                    default=DEFAULT_CHAT_MODEL,
                ): str,
                vol.Optional(
                    CONF_MAX_TOKENS,
                    default=DEFAULT_MAX_TOKENS,
                ): int,
                vol.Optional(
                    CONF_ADVANCED_OPTIONS,
                    default=DEFAULT_ADVANCED_OPTIONS,
                ): BooleanSelector(),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(schema), self.options
            ),
        )

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle advanced options step."""
        if user_input is not None:
            # Merge advanced options with temp data
            final_data = {**(self._temp_data or {}), **user_input}

            if self._is_new:
                title = final_data.get(CONF_NAME, DEFAULT_AI_TASK_NAME)
                final_data.pop(CONF_NAME, None)
                return self.async_create_entry(
                    title=title,
                    data=final_data,
                )
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                data=final_data,
            )

        # Build schema for advanced options based on selected model
        chat_model = (self._temp_data or {}).get(CONF_CHAT_MODEL, DEFAULT_CHAT_MODEL)
        model_config = get_model_config(
            chat_model, self._get_entry().data.get(CONF_BASE_URL)
        )

        schema: dict[Any, Any] = {}

        # Add top_p if supported
        if model_config["supports_top_p"]:
            schema[
                vol.Optional(
                    CONF_TOP_P,
                    default=DEFAULT_TOP_P,
                )
            ] = NumberSelector(NumberSelectorConfig(min=0, max=1, step=0.05))

        # Add temperature if supported
        if model_config["supports_temperature"]:
            schema[
                vol.Optional(
                    CONF_TEMPERATURE,
                    default=DEFAULT_TEMPERATURE,
                )
            ] = NumberSelector(NumberSelectorConfig(min=0, max=2, step=0.05))

        # Add reasoning_effort if supported (o1, o3, o4, gpt-5 models)
        if model_config.get("supports_reasoning_effort"):
            schema[
                vol.Optional(
                    CONF_REASONING_EFFORT,
                    default=DEFAULT_REASONING_EFFORT,
                )
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=opt, label=opt.capitalize())
                        for opt in REASONING_EFFORT_OPTIONS
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )

        # Add service_tier if supported (o3, o4, gpt-5 models)
        if model_config.get("supports_service_tier"):
            schema[
                vol.Optional(
                    CONF_SERVICE_TIER,
                    default=DEFAULT_SERVICE_TIER,
                )
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=opt, label=opt.capitalize())
                        for opt in SERVICE_TIER_OPTIONS
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )

        # Add extra_body - passthrough for OpenAI-compatible backends
        # (ollama, llama.cpp, vLLM, LM Studio). Accepts a Jinja-templatable
        # JSON string; empty disables.
        schema[
            vol.Optional(
                CONF_EXTRA_BODY,
                default=DEFAULT_EXTRA_BODY,
            )
        ] = TemplateSelector()

        # Add shorten_tool_call_id option (for Mistral AI compatibility)
        schema[
            vol.Optional(
                CONF_SHORTEN_TOOL_CALL_ID,
                default=DEFAULT_SHORTEN_TOOL_CALL_ID,
            )
        ] = BooleanSelector()

        return self.async_show_form(
            step_id="advanced",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(schema), self.options
            ),
        )
