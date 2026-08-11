from django.http import FileResponse, Http404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import decorators, filters, mixins, serializers, status, viewsets
from rest_framework.response import Response

from apps.accounts.permissions import IsActiveTenantMember
from apps.billing.exceptions import InsufficientCredits, ProcessingPriceNotConfigured

from .exceptions import (
    MapJobEnqueueError,
    MapJobIdempotencyConflict,
    MapJobTransitionConflict,
)
from .models import GeneratedMap, IndexType, MapJob
from .serializers import (
    GeneratedMapSerializer,
    MapJobCreateSerializer,
    MapJobSerializer,
)
from .services import create_map_job
from .services.lifecycle import cancel_map_job, reprocess_map_job


class MapJobViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = (IsActiveTenantMember,)
    filter_backends = (filters.SearchFilter, filters.OrderingFilter)
    search_fields = ("property__name", "stac_item_id", "current_step")
    ordering_fields = ("created_at", "finished_at", "progress", "status")
    ordering = ("-created_at",)

    @staticmethod
    def _idempotency_key(request) -> str:
        idempotency_key = request.headers.get("Idempotency-Key", "").strip()
        if not idempotency_key:
            raise serializers.ValidationError(
                {"Idempotency-Key": "Este header é obrigatório."}
            )
        if len(idempotency_key) > 160:
            raise serializers.ValidationError(
                {"Idempotency-Key": "Use no máximo 160 caracteres."}
            )
        return idempotency_key

    def get_queryset(self):
        queryset = MapJob.objects.select_related(
            "property", "created_by", "generated_map"
        ).all()
        requested_status = self.request.query_params.get("status")
        index_type = self.request.query_params.get("index_type")
        if requested_status in MapJob.Status.values:
            queryset = queryset.filter(status=requested_status)
        if index_type in IndexType.values:
            queryset = queryset.filter(index_type=index_type)
        return queryset

    def get_serializer_class(self):
        if self.action == "create":
            return MapJobCreateSerializer
        return MapJobSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="Idempotency-Key",
                location=OpenApiParameter.HEADER,
                required=True,
                type=str,
                description="Chave única da solicitação, com até 160 caracteres.",
            )
        ],
        request=MapJobCreateSerializer,
        responses={
            202: MapJobSerializer,
            402: OpenApiResponse(description="Saldo de créditos insuficiente."),
            409: OpenApiResponse(
                description="Conflito de idempotência ou preço ausente."
            ),
            503: OpenApiResponse(description="Fila de processamento indisponível."),
        },
    )
    def create(self, request, *args, **kwargs):
        idempotency_key = self._idempotency_key(request)

        input_serializer = MapJobCreateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        try:
            job, replayed = create_map_job(
                created_by=request.user,
                idempotency_key=idempotency_key,
                **input_serializer.validated_data,
            )
        except InsufficientCredits as exc:
            return Response(
                {"code": "insufficient_credits", "detail": str(exc)},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )
        except ProcessingPriceNotConfigured as exc:
            return Response(
                {"code": "price_not_configured", "detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        except MapJobIdempotencyConflict as exc:
            return Response(
                {"code": "idempotency_conflict", "detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        except MapJobEnqueueError as exc:
            return Response(
                {"code": "queue_unavailable", "detail": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        output = MapJobSerializer(job, context={"request": request})
        response = Response(output.data, status=status.HTTP_202_ACCEPTED)
        response["Idempotent-Replayed"] = str(replayed).lower()
        return response

    @extend_schema(
        request=None,
        responses={
            200: MapJobSerializer,
            409: OpenApiResponse(description="Job já terminal e não cancelável."),
        },
    )
    @decorators.action(detail=True, methods=("post",), url_path="cancel")
    def cancel(self, request, *args, **kwargs):
        source = self.get_object()
        try:
            job, replayed = cancel_map_job(
                job_id=source.id,
                cancelled_by=request.user,
            )
        except MapJobTransitionConflict as exc:
            return Response(
                {"code": "job_not_cancellable", "detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        response = Response(MapJobSerializer(job, context={"request": request}).data)
        response["Idempotent-Replayed"] = str(replayed).lower()
        return response

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="Idempotency-Key",
                location=OpenApiParameter.HEADER,
                required=True,
                type=str,
                description="Chave única do reprocessamento, com até 160 caracteres.",
            )
        ],
        request=None,
        responses={
            202: MapJobSerializer,
            402: OpenApiResponse(description="Saldo de créditos insuficiente."),
            409: OpenApiResponse(description="Transição ou idempotência inválida."),
            503: OpenApiResponse(description="Fila de processamento indisponível."),
        },
    )
    @decorators.action(detail=True, methods=("post",), url_path="reprocess")
    def reprocess(self, request, *args, **kwargs):
        idempotency_key = self._idempotency_key(request)
        source = self.get_object()
        try:
            job, replayed = reprocess_map_job(
                source_job=source,
                created_by=request.user,
                idempotency_key=idempotency_key,
            )
        except MapJobTransitionConflict as exc:
            return Response(
                {"code": "job_not_reprocessable", "detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        except InsufficientCredits as exc:
            return Response(
                {"code": "insufficient_credits", "detail": str(exc)},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )
        except ProcessingPriceNotConfigured as exc:
            return Response(
                {"code": "price_not_configured", "detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        except MapJobIdempotencyConflict as exc:
            return Response(
                {"code": "idempotency_conflict", "detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        except MapJobEnqueueError as exc:
            return Response(
                {"code": "queue_unavailable", "detail": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        response = Response(
            MapJobSerializer(job, context={"request": request}).data,
            status=status.HTTP_202_ACCEPTED,
        )
        response["Idempotent-Replayed"] = str(replayed).lower()
        return response


class GeneratedMapViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = (IsActiveTenantMember,)
    serializer_class = GeneratedMapSerializer
    filter_backends = (filters.SearchFilter, filters.OrderingFilter)
    search_fields = ("property__name", "stac_item_id")
    ordering_fields = ("created_at", "scene_date", "cloud_cover")
    ordering = ("-created_at",)

    def get_queryset(self):
        queryset = GeneratedMap.objects.select_related(
            "job", "property", "created_by"
        ).all()
        index_type = self.request.query_params.get("index_type")
        if index_type in IndexType.values:
            queryset = queryset.filter(index_type=index_type)
        return queryset

    def _download(self, file_format: str):
        generated_map = self.get_object()
        file_field = (
            generated_map.png_file if file_format == "png" else generated_map.pdf_file
        )
        try:
            stream = file_field.open("rb")
        except (FileNotFoundError, OSError) as exc:
            raise Http404("Arquivo do mapa não encontrado.") from exc
        return FileResponse(
            stream,
            as_attachment=True,
            filename=f"delta-mapas-{generated_map.id}.{file_format}",
            content_type=("image/png" if file_format == "png" else "application/pdf"),
        )

    @extend_schema(responses={(200, "image/png"): OpenApiTypes.BINARY})
    @decorators.action(detail=True, methods=("get",), url_path="download/png")
    def download_png(self, request, *args, **kwargs):
        return self._download("png")

    @extend_schema(responses={(200, "application/pdf"): OpenApiTypes.BINARY})
    @decorators.action(detail=True, methods=("get",), url_path="download/pdf")
    def download_pdf(self, request, *args, **kwargs):
        return self._download("pdf")
