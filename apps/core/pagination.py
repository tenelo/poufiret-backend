"""Pagination standard de l'API Poufiret."""
from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """PageNumber classique, mais le client peut demander ?page_size=N (max 100)."""
    page_size_query_param = 'page_size'
    max_page_size = 100
