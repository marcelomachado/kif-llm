# LLM Store #

A Wikidata-view over Large Language Models.

## What is it? ##
[KIF](https://github.com/IBM/kif) is a framework designed for integrating diverse knowledge sources, including RDF-based interfaces, relational databases and, CSV files. It leverages the Wikidata's data model to expose a unified view of the integrated sources. The result is a virtual knowledge base which behaves like an "extended Wikidata" that can be queried through a lightweight query interface. More details about KIF can be found in [this paper](https://arxiv.org/abs/2403.10304).

For a data source to be accessed via KIF filters, i.e. KIF's query interface, it is necessary to create a `Store` that, based on user-defined mappings, will enable access to the underlying data source in its native language.

LLM Store is a KIF Store whose underlying data sources are LLMs.

LLM Store is powered by [LangChain](https://www.langchain.com/langchain)!


## Getting started ##

### Installation ###

#### Using this repository ####

1. Clone this repository:

  ```bash
  git clone https://github.com/IBM/kif-llm-store
  cd kif-llm-store
  ```

2. Create a virtual environment and activate it. Install the requirements:

  ```bash
  pip install -r requirements.txt
  ```

3. Set the environment variables
  ```
  LLM_API_KEY=your_api_key
  LLM_API_ENDPOINT=platform_endpoint
  ```

#### Using PyPI (soon) ####

```
pip install kif-llm-store
```
---

To instantiate an LLM Store it is necessary to indicate a LLM provider to access models. The LLM provider can be `open_ai` to access models from OpenAI, `ibm` to access models from IBM WatsonX, and `ollama` to access models from [Ollama](https://ollama.com/). Depending on the plataform selected you need to provide the credentials to access it.

### Imports: ###

```python
# Import KIF namespacee
from kif_lib import *
# Import LLM Store main abstraction
from kif_llm_store import LLM_Store
# Import LLM Providers identifiers to set the LLM Provider in which the LLM Store will run over.
from kif_llm_store.store.llm.constants import LLM_Providers
```

### Instantiate it: ###

```python
# Using IBM WatsonX models
kb = Store(LLM_Store.store_name,
    llm_provider=LLM_Providers.IBM,
    model_id='meta-llama/llama-3-70b-instruct',
    api_key=os.environ['LLM_API_KEY'],
    base_url=os.environ['LLM_API_ENDPOINT'],
    project_id =os.environ['WATSONX_PROJECT_ID'],
)
```
```python
# Using OpenAI models
kb = Store(LLM_Store.store_name,
    llm_provider=LLM_Providers.OPEN_AI,
    model_id='gpt-4o',
    api_key=os.environ['LLM_API_KEY'],
)
```

You can instantiate LLM Store direct with a [LangChain Chat Model](https://python.langchain.com/v0.2/api_reference/core/language_models/langchain_core.language_models.chat_models.BaseChatModel.html), for instance:

```python
# Import LangChain OpenAI Integration
from langchain_openai import ChatOpenAI

# Instantiate a LangChain model for OpenAI
model = ChatOpenAI(model='gpt-3.5-turbo', api_key=os.environ['LLM_API_KEY'])

# Instantiate a LLM Store passing the model as a parameter
kb = Store(LLM_Store.store_name, model=model)
```

This approach enables you to run LLM Store with any LangChain Integration not only the models listed in `LLM_Providers`.

## Hello World ##

Matches statements where the subject is the Wikidata Item representing the entity `Brazil` and the property is the Wikidata Property for `shares border with`. This filter should retrieves statements linking [Brazil](https://www.wikidata.org/wiki/Q155) to other items through the property [share a border with](https://www.wikidata.org/wiki/Property:P47) it:

```python
# Import Wikidata vocabulary from kif_lib
from kif_lib.vocabulary import wd

# Filter statements where the subject is the item `Brazil` and the property is `shares border with`.
stmts = kb.filter(subject=wd.Brazil, property=wd.shares_border_with, limit=10)
for stmt in stmts:
    display(stmt)
```

## Documentation ##

See [documentation](https://ibm.github.io/kif-llm/) and [examples](./examples).


## Citation ##

Machado, M., Rodrigues, J. M., Lima, G., Fiorini, S. R., & da Silva, V. T. (2024, November). **LLM Store: Leveraging Large Language Models as Sources of Wikidata-Structured Knowledge.** In *International Semantic Web Conference*.

## ISWC LM-KBC 2024 Challenge
Our LLM Store solution to the [ISWC LM-KBC 2024 Challenge](https://lm-kbc.github.io/challenge2024/) can be [accessed here](https://github.com/IBM/kif-llm/tree/lm-kbc-challenge).


## License ##

Released under the [Apache-2.0 license](./LICENSE).
