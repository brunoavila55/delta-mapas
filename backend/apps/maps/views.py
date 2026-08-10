from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.response import Response

from apps.accounts.permissions import IsActiveTenantMember
from apps.billing.exceptions import InsufficientCredits, ProcessingPriceNotConfigured

from .exceptions import MapJobEnqueueError, MapJobIdempotencyConflict
from .models import IndexType, MapJob
from .serializers import MapJobCreateSerializer, MapJobSerializer
from .services import create_map_job


class MapJobViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = (IsActiveTenantMember,)

    def get_queryset(self):
        queryset = MapJob.objects.select_related("property", "created_by").all()
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
        idempotency_key = request.headers.get("Idempotency-Key", "").strip()
        if not idempotency_key:
            raise serializers.ValidationError(
                {"Idempotency-Key": "Este header é obrigatório."}
            )
        if len(idempotency_key) > 160:
            raise serializers.ValidationError(
                {"Idempotency-Key": "Use no máximo 160 caracteres."}
            )

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
