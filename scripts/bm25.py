"""Small article-level BM25 baseline; no external search service required."""
import math
import re
from collections import Counter


def tokenize(text):
    return re.findall(r"[\wÀ-ỹ]+", (text or "").casefold(), flags=re.UNICODE)


class BM25Index:
    def __init__(self, documents, k1=1.2, b=0.75):
        self.documents = list(documents)
        self.k1, self.b = k1, b
        self.tokens = [tokenize(doc.get("text", "")) for doc in self.documents]
        self.lengths = [len(tokens) for tokens in self.tokens]
        self.average_length = sum(self.lengths) / max(len(self.lengths), 1)
        self.document_frequency = Counter()
        for tokens in self.tokens:
            self.document_frequency.update(set(tokens))

    def search(self, query, limit=10):
        terms = tokenize(query)
        scores = []
        total = len(self.documents)
        for index, tokens in enumerate(self.tokens):
            counts = Counter(tokens)
            score = 0.0
            for term in terms:
                if term not in counts:
                    continue
                df = self.document_frequency[term]
                idf = math.log(1 + (total - df + 0.5) / (df + 0.5))
                denominator = counts[term] + self.k1 * (1 - self.b + self.b * self.lengths[index] / max(self.average_length, 1))
                score += idf * counts[term] * (self.k1 + 1) / denominator
            if score:
                scores.append((score, index))
        scores.sort(key=lambda item: (-item[0], item[1]))
        return [{**self.documents[index], "score": score, "rank": rank} for rank, (score, index) in enumerate(scores[:limit], 1)]
