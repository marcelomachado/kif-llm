# Copyright (C) 2025 IBM Corp.
# SPDX-License-Identifier: Apache-2.0

import logging
import asyncio
from kif_lib.store.abc import TOptions
import nest_asyncio
from typing import List, Dict
import importlib.util

from kif_lib import (
    Entity,
    Filter,
    Item,
    Property,
    QuantityDatatype,
    TimeDatatype,
    StringDatatype,
    TextDatatype,
    Statement,
    Store,
    Value,
    ValueSnak,
    Search
)

from kif_lib.typing import (
    Any,
    AsyncIterator,
    ClassVar,
    Iterable,
    Iterator,
    Optional,
    Union,
    override,
)

from kif_lib.model.fingerprint import (
    OrFingerprint,
    ValueFingerprint,
)

from .language_models import BaseChatModel
from .output_parsers import (
    SemicolonSeparatedListOfNumbersOutputParser,
    SemicolonSeparatedListOfDateTimeOutputParser,
    SemicolonSeparatedListOutputParser,
    BaseOutputParser,
)
from .prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableSequence

from .compiler.llm.filter_compiler import (
    LLM_FilterCompiler,
    Variable,
    LogicalComponent,
)

from .constants import (
    DEFAULT_AVOID_EXPLANATION_INSTRUCTION,
    DEFAULT_SYSTEM_PROMPT_INSTRUCTION,
    SYSTEM_PROMPT_INSTRUCTION_WITH_CONTEXT,
    SYSTEM_PROMPT_INSTRUCTION_WITH_ENFORCED_CONTEXT,
    EntityLinkingMethod,
    KIF_FilterTypes,
    LLM_Providers,
)

nest_asyncio.apply()

LOG = logging.getLogger(__name__)


class PromptExample:
    """Example.

    Parameters:
        subject: Entity.
        property: Property.
        value: Value
    """

    def __init__(self, subject: Entity, property: Property, value: Value):
        assert subject
        assert property
        assert value

        self._subject = subject
        self._property = property
        self._value = value


class LLM_Store(
    Store[TOptions],
    store_name='llm',
    store_description=(
        'KIF Store powered by Large Language Models.'
        'Disclaimer: LLMs can make mistakes. Double check important info.'
    ),
):
    """LLM Store

    .. Setup::

        Install ``llm-store`` and set the models you want to use from LLM Store.

        .. code-block:: bash

            pip install -e .
            pip install -U kif-llm

    Properties::
      store_name: Store plugin to instantiate.
      model: An LLM model instance (it accepts an intance of a LangChain BaseChatModel).
      llm_provider: The identifier of an LLM provider to be used, such as `ibm` for IBM WatsonX.
      model_id: LLM model identifier (e.g., meta-llama/llama-3-8b-instruct).
      base_url: Endpoint to access the LLM provider.
      api_key: API Key to access the LLM provider.
      task_prompt_template: Prompt template to replace the internal (default)
        task prompt template.
      parser: A parser instance (it accepts an instance of a LangChain BaseOutputParser).
      textual_context: Text to In-Context Prompting.
      examples: A list of PromptExamples to be used as FewShot examples.
      entity_linking_method: The identifier of an Entity Linking method to be used, such as `llm`
        for LLM-based method.
      model_for_entity_resolution: If the `entity_linking_method` used is LLM-based than this parameter
        may be used to indicate the LLM mode to use (it accepts an intance of a LangChain BaseChatModel).
      target_store: A KIF Store
      searcher: A KIF Searcher to perform lookup searches for entities
      enforce_context: Whether to enforce LLM to search the answer
        in context or use the context to support the answer
      model_args: Arguments to the LLM model, e.g. {'max_new_tokens': 2048}
    """  # noqa E501

    __slots__ = (
        '_model',
        '_task_prompt_template',
        '_parser',
        '_textual_context',
        '_examples',
        '_entity_linking_method',
        '_model_for_entity_resolution',
        '_target_store',
        '_searcher',
        '_output_format_prompt',
        '_enforce_context',
        '_compile_to_natural_language_question',
        '_create_entity',
        '_compiler',
    )

    _model: BaseChatModel
    _task_prompt_template: Optional[str]
    _parser: Optional[BaseOutputParser]
    _textual_context: Optional[str]
    _entity_linking_method: Optional[EntityLinkingMethod]
    _target_store: Store
    _searcher: Search
    _model_for_entity_resolution: Optional[BaseChatModel]
    _examples: Optional[List[PromptExample]]
    _output_format_prompt: Optional[str]
    _compiler: LLM_FilterCompiler

    def __init__(
        self,
        store_name: str,
        target_store: Store,
        searcher: Search,
        model: Optional[BaseChatModel] = None,
        llm_provider: Optional[LLM_Providers] = None,
        model_id: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        task_prompt_template: Optional[str] = None,
        output_format_prompt: Optional[str] = None,
        parser: Optional[BaseOutputParser] = None,
        textual_context: Optional[str] = None,
        examples: Optional[List[PromptExample]] = None,
        entity_linking_method: Optional[EntityLinkingMethod] = None,
        model_for_entity_resolution: Optional[BaseChatModel] = None,

        enforce_context=False,
        compile_to_natural_language_question=False,
        create_entity=False,
        model_params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(store_name, **kwargs)
        assert store_name == self.store_name

        if model:
            self._model = model
        else:
            self._model = LLM_Store._init_model(
                llm_provider=llm_provider,
                model_id=model_id,
                base_url=base_url,
                api_key=api_key,
                model_params=model_params,
                **kwargs,
            )

        default_parser_fn = SemicolonSeparatedListOutputParser()
        self._parser = parser or default_parser_fn
        self._output_format_prompt = (
            output_format_prompt or default_parser_fn.get_format_instructions()
        )

        self._model_for_entity_resolution = (
            model_for_entity_resolution or self._model
        )
        self._entity_linking_method = (
            entity_linking_method or EntityLinkingMethod.NAIVE
        )

        self._task_prompt_template = task_prompt_template

        self._textual_context = textual_context

        self._examples = examples

        self._enforce_context = enforce_context

        self._compile_to_natural_language_question = (
            compile_to_natural_language_question
        )
        self._create_entity = create_entity

        self._target_store = target_store

        self._searcher = searcher
    @classmethod
    def from_model_providers_args(
        cls,
        llm_provider: LLM_Providers,
        model_id: str,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        entity_linking_method: Optional[EntityLinkingMethod] = None,
        *args,
        **model_kwargs: Any,
    ):
        model = cls._init_model(
            llm_provider=llm_provider,
            model_id=model_id,
            base_url=base_url, # type: ignore
            api_key=api_key, # type: ignore
            **model_kwargs,
        )

        return cls(
            store_name="llm",
            model=model,
            entity_linking_method=entity_linking_method,
            *args,
            **model_kwargs,
        )

    @classmethod
    def _init_model(
        cls,
        llm_provider: LLM_Providers,
        model_id: str,
        base_url: str,
        api_key: str,
        model_params: Optional[Dict[str, Any]] = {},
        **kwargs,
    ) -> BaseChatModel:
        assert llm_provider, "No LLM provider was set."
        assert llm_provider in LLM_Providers, "Invalid LLM provider."
        assert model_id, "No model identifier was set."

        llm_params: Dict[str, Any] = {
            "base_url": base_url,
            "api_key": api_key,
        }

        try:
            if llm_provider == LLM_Providers.OPEN_AI:
                from langchain_openai import ChatOpenAI

                return ChatOpenAI(
                    model=model_id, **{**llm_params, **model_params, **kwargs}
                )
            elif llm_provider == LLM_Providers.OLLAMA:
                from langchain_ollama import ChatOllama

                return ChatOllama(
                    model=model_id, **{**llm_params, **model_params, **kwargs}
                )
            elif llm_provider == LLM_Providers.IBM:
                pack = 'langchain_ibm'
                if importlib.util.find_spec(pack) is None:
                    print(f'Package {pack} not installed.')
                    print(f'Please, install it using: pip install {pack}')
                    raise ValueError(f"Package {pack} not installed.")
                else:
                    from langchain_ibm import ChatWatsonx

                    return ChatWatsonx(
                        model_id=model_id,
                        apikey=api_key, # type: ignore
                        url=base_url, # type: ignore
                        params=model_params,
                        **kwargs,
                    )
            else:
                raise ValueError(f"Unsupported provider: {llm_provider}")
        except Exception as e:
            raise e

    @property
    def model(self) -> BaseChatModel:
        return self._model

    @model.setter
    def model(self, value: BaseChatModel) -> None:
        self._model = value

    @property
    def target_store(self) -> Store:
        return self._target_store

    @target_store.setter
    def target_store(self, value: Store) -> None:
        self._target_store = value

    @property
    def searcher(self) -> Search:
        return self._searcher

    @searcher.setter
    def searcher(self, value: Search) -> None:
        self._searcher = value

    @property
    def task_prompt_template(
        self,
    ) -> Optional[str]:
        return self._task_prompt_template

    @task_prompt_template.setter
    def task_prompt_template(self, value: str) -> None:
        self._task_prompt_template = value

    @property
    def output_format_prompt(self) -> Optional[str]:
        return self._output_format_prompt

    @output_format_prompt.setter
    def output_format_prompt(self, value: str) -> Optional[str]:
        self._output_format_prompt = value

    @property
    def parser(self) -> Optional[BaseOutputParser]:
        return self._parser

    @parser.setter
    def parser(self, value: BaseOutputParser) -> None:
        self._parser = value

    @property
    def entity_linking_method(self) -> EntityLinkingMethod:
        return self._entity_linking_method

    @entity_linking_method.setter
    def entity_linking_method(self, value: EntityLinkingMethod) -> None:
        self._entity_linking_method = value

    @property
    def enforce_context(self) -> bool:
        return self._enforce_context

    @enforce_context.setter
    def enforce_context(self, value: bool) -> None:
        self._enforce_context = value

    @property
    def compile_to_natural_language_question(self) -> bool:
        return self._compile_to_natural_language_question

    @compile_to_natural_language_question.setter
    def compile_to_natural_language_question(self, value: bool) -> None:
        self._compile_to_natural_language_question = value

    @property
    def create_entity(self) -> bool:
        return self._create_entity

    @create_entity.setter
    def create_entity(self, value: bool) -> None:
        self._create_entity = value

    @property
    def textual_context(self) -> Optional[str]:
        return self._textual_context

    @textual_context.setter
    def textual_context(self, value: str) -> None:
        self._textual_context = value

    @property
    def examples(self) -> Optional[List[PromptExample]]:
        return self._examples

    @examples.setter
    def examples(self, value: List[PromptExample]) -> None:
        self._examples = value

    def add_examples(self, examples: List[PromptExample]) -> None:
        if not self._examples:
            self._examples = []

        self._examples.extend(examples)

    @override
    def _filter(
        self, filter: Filter, options: TOptions
    ) -> Iterator[Statement]:

        async def sync_wrapper() -> List[Statement]:
            results = []
            async for stmt in self._afilter(filter, options):
                results.append(stmt)
            return results

        return iter(asyncio.run(sync_wrapper()))

    async def _afilter(
        self, filter: Filter, options: TOptions
    ) -> AsyncIterator[Statement]:

        assert (
            filter.property
        ), 'LLM Store can not handle filters with undefined property yet.'

        s = filter.subject
        p = filter.property
        v = filter.value

        new_filter: Filter
        # TODO decompose complex compound filters (it should be handled on KIF's layer)  # noqa E501
        if isinstance(s, OrFingerprint):
            for sub_filter in s:
                new_filter = Filter(sub_filter, filter.property, filter.value)
                async for result in self._afilter(
                    new_filter, options
                ):
                    yield result
        elif isinstance(v, OrFingerprint):
            for sub_filter in v:
                new_filter = Filter(
                    filter.subject, filter.property, sub_filter
                )
                async for result in self._afilter(
                    new_filter, options
                ):
                    yield result
        elif isinstance(p, OrFingerprint):
            for sub_filter in p:
                new_filter = Filter(filter.subject, sub_filter, filter.value)
                async for result in self._afilter(
                    new_filter, options
                ):
                    yield result
        else:
            self._parser = SemicolonSeparatedListOutputParser()
            self._output_format_prompt = self._parser.get_format_instructions()

            # TODO create conditions for each datatype different from Item,
            # such as TimeDatatype
            if isinstance(p, ValueFingerprint):
                if isinstance(p[0].range, QuantityDatatype):
                    self._parser = (
                        SemicolonSeparatedListOfNumbersOutputParser()
                    )
                    self._output_format_prompt = (
                        self._parser.get_format_instructions()
                    )
                elif isinstance(p[0].range, TimeDatatype):
                    self._parser = (
                        SemicolonSeparatedListOfDateTimeOutputParser()
                    )
                    self._output_format_prompt = (
                        self._parser.get_format_instructions()
                    )

            self._compiler = self._compile_filter(filter, options)
            query = self._compiler.query_template

            if self.examples:
                pass

            if (
                self._compiler.get_filter_type()
                == KIF_FilterTypes.ONE_VARIABLE
            ):
                replacement = '_'
                if self._compiler.has_where:
                    replacement = 'X'
                query = self._compiler.query_template.replace(
                    'var1', replacement
                )

            chain = self._create_pipline_chain(distinct=options.distinct, limit=options.limit or 10)

            try:
                async for statement in await chain.ainvoke(
                    {
                        'query': query,
                        'textual_context': self.textual_context,
                        'examples': self.examples,
                    }
                ):
                    yield statement
            except Exception as e:
                raise e

    #: Flags to be passed to filter compiler.
    _compile_filter_flags: ClassVar[LLM_FilterCompiler.Flags] = (
        LLM_FilterCompiler.default_flags
    )

    def _compile_filter(
        self, filter: Filter, options: TOptions
    ) -> LLM_FilterCompiler:
        compiler = LLM_FilterCompiler(filter, self._target_store, self._compile_filter_flags)

        compiler.compile(self.task_prompt_template)
        return compiler

    def _create_pipline_chain(
        self, limit = 10, distinct=True
    ) -> RunnableSequence:
        from langchain_core.runnables import RunnableLambda

        def distinct_fn(labels: List[str]) -> List[str]:
            if distinct:
                labels = list(set(labels))
            return labels[:limit]

        debug_chain = RunnableLambda(lambda entry: (LOG.info(entry), entry)[1])

        prompt = self._build_prompt_template()

        do_distinct = RunnableLambda(distinct_fn)

        disambiguate = RunnableLambda(
            lambda labels: self._disambiguate(labels)
        )

        to_statements = RunnableLambda(
            lambda binds: self._to_statements(binds)
        )

        chain: RunnableSequence = (
            prompt
            | debug_chain
            | self.model
            | debug_chain
            | self.parser
            | debug_chain
            | do_distinct
            | debug_chain
            | disambiguate
            | debug_chain
            | to_statements
            | debug_chain
        )

        if self.compile_to_natural_language_question:
            from ..llm.query_to_question import QueryToQuestion

            q2q = QueryToQuestion(model=self.model)

            chain = (
                RunnableLambda(lambda query: q2q.run(query))
                | debug_chain
                | RunnableLambda(
                    lambda question: {
                        'query': question,
                        'textual_context': self.textual_context,
                        'examples': self.examples,
                    }
                )
            ) | chain

        return chain

    async def _disambiguate(
        self, labels: List[str]
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Asynchronously disambiguates labels.
        """
        binds = self._compiler.get_binds()

        from kbel.disambiguators import (
            Disambiguator,
            SimpleDisambiguator,
            LLM_Disambiguator,
        )

        disambiguator: Disambiguator = Disambiguator('simple')
        if self.entity_linking_method == EntityLinkingMethod.LLM:
            if (
                self._compiler.get_filter_type()
                == KIF_FilterTypes.ONE_VARIABLE
            ):
                sentence = self._compiler.get_task_sentence_template().replace(
                    'var1', '{{term}}'
                )
                disambiguator = Disambiguator('llm', model=self._model_for_entity_resolution)
                disambiguator.disambiguate_property(label, searcher=self.searcher, sentence=sentence)

        if isinstance(binds['property'], Variable):
            async for _, entity in disambiguator.disambiguate_property(
                labels, cls=Property
            ):  # noqa: E501
                binds['property'].set_value(entity)
                yield binds
        else:
            if isinstance(binds['value'], Variable):
                p: Property = binds['property']

                if (
                    isinstance(p.range, QuantityDatatype)
                    or isinstance(p.range, StringDatatype)
                    or isinstance(p.range, TextDatatype)
                ):
                    for label in labels:
                        binds['value'].set_value(label)
                        yield binds
                else:
                    async for (
                        label,
                        entity,
                    ) in disambiguator.adisambiguate(
                        labels
                    ):  # noqa: E501
                        if not entity and self.create_entity:
                            entity = self._create_new_item(label)
                        if isinstance(binds['value'], Variable):
                            binds['value'].set_value(entity)
                        yield binds
            else:
                async for _, entity in disambiguator.adisambiguate(
                    labels
                ):  # noqa: E501
                    if isinstance(binds['subject'], Variable):
                        binds['subject'].set_value(entity)
                    yield binds

    async def _to_statements(
        self, binds: Dict[str, Any]
    ) -> AsyncIterator[Statement]:

        async for bind in binds:

            def get_entity(key: str):
                if isinstance(bind[key], Variable):
                    entity = bind[key].get_value()
                    if entity:
                        return bind[key].get_value()
                    # if self._create_entity:
                    # TODO: create item
                    return None
                return bind[key]

            subject = get_entity('subject')
            if not subject:
                continue
            property = get_entity('property')
            if not property:
                continue
            value = get_entity('value')
            if not value:
                continue

            value_snaks = []
            if isinstance(value, LogicalComponent):
                for component in value.components:
                    value_snaks.append(
                        ValueSnak(
                            property=property,
                            value=component,
                        )
                    )
            else:
                value_snaks.append(
                    ValueSnak(
                        property=property,
                        value=value,
                    )
                )

            if isinstance(subject, LogicalComponent):
                for component in subject.components:
                    for vs in value_snaks:
                        stmt = Statement(component, vs)
                        yield stmt

            else:
                for vs in value_snaks:
                    stmt = Statement(subject, vs)
                    yield stmt

    def _create_new_item(
        self,
        label: str,
        type='item',
    ) -> Entity:
        assert type in ['item', 'property']

        import hashlib
        import os

        random_bytes = os.urandom(32)
        hash_object = hashlib.sha256()
        hash_object.update(random_bytes)
        hash_digest = hash_object.hexdigest()

        iri = f'https://github.com/IBM/kif-llm/{hash_digest}'
        if type == 'item':
            return Item(iri)
        return Property(iri)

    def _get_examples_for_property(
        self, property: Property
    ) -> Iterator[Statement]:
        self._searcher

    def _build_prompt_template(self) -> ChatPromptTemplate:
        from langchain_core.messages import SystemMessage

        system = DEFAULT_SYSTEM_PROMPT_INSTRUCTION

        human = ''
        if self.textual_context:
            system = SYSTEM_PROMPT_INSTRUCTION_WITH_CONTEXT
            human += '''CONTEXT:
"{textual_context}"

'''
            if self.enforce_context:
                system = SYSTEM_PROMPT_INSTRUCTION_WITH_ENFORCED_CONTEXT

        system += f' {self.output_format_prompt} {DEFAULT_AVOID_EXPLANATION_INSTRUCTION}'  # noqa E501

        if self.examples:
            human += 'TASK:\n{formatted_examples}'
        else:
            human += '''TASK:\n{query}'''

        return ChatPromptTemplate.from_messages(
            [SystemMessage(content=system), ('human', human)]
        )
