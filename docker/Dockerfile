# Elasticsearch
ARG ES_VERSION=9.5.3
FROM elasticsearch:${ES_VERSION}

# analysis-ik
ARG ES_VERSION
RUN bin/elasticsearch-plugin install --batch \
      https://release.infinilabs.com/analysis-ik/stable/elasticsearch-analysis-ik-${ES_VERSION}.zip
