import { toast } from 'sonner'

export interface ApiError {
  status: number
  message: string
  detail?: string
  code?: string
}

const STATUS_MESSAGES: Record<number, string> = {
  400: 'La solicitud contiene datos inválidos.',
  401: 'No autorizado. Por favor inicia sesión de nuevo.',
  403: 'No tienes permiso para realizar esta acción.',
  404: 'El recurso solicitado no fue encontrado.',
  409: 'El recurso ya existe o hay un conflicto.',
  413: 'El archivo es demasiado grande.',
  422: 'Los datos enviados no son válidos.',
  429: 'Demasiadas solicitudes. Por favor espera un momento.',
  500: 'Error interno del servidor.',
  502: 'El servidor no está disponible temporalmente.',
  503: 'El servicio no está disponible en este momento.',
}

function getStatusMessage(status: number): string {
  return STATUS_MESSAGES[status] ?? `Error del servidor (${status}).`
}

async function tryParseJson(text: string): Promise<Record<string, unknown> | null> {
  try {
    return JSON.parse(text) as Record<string, unknown>
  } catch {
    return null
  }
}

export async function parseApiError(error: unknown): Promise<ApiError> {
  if (error instanceof Response) {
    const text = await error.text().catch(() => '')
    const body = text ? await tryParseJson(text) : null
    const detailValue = body?.detail
    const detail =
      typeof detailValue === 'string'
        ? detailValue
        : detailValue && typeof detailValue === 'object' && 'error' in detailValue
          ? typeof detailValue.error === 'object' &&
            detailValue.error !== null &&
            'message' in detailValue.error &&
            typeof detailValue.error.message === 'string'
            ? detailValue.error.message
            : undefined
          : undefined
    const code =
      detailValue && typeof detailValue === 'object' && 'error' in detailValue &&
      typeof detailValue.error === 'object' && detailValue.error !== null &&
      'code' in detailValue.error && typeof detailValue.error.code === 'string'
        ? detailValue.error.code
        : undefined
    return {
      status: error.status,
      message: getStatusMessage(error.status),
      detail,
      code,
    }
  }

  if (error instanceof TypeError && error.message === 'Failed to fetch') {
    return {
      status: 0,
      message: 'No se pudo conectar con el servidor.',
    }
  }

  if (error instanceof Error) {
    return {
      status: 0,
      message: error.message,
    }
  }

  return {
    status: 0,
    message: 'Ocurrió un error inesperado.',
  }
}

export async function handleApiError(
  error: unknown,
  options?: { silent?: boolean }
): Promise<ApiError> {
  const apiError = await parseApiError(error)

  // Don't show toasts for 401 — auth redirect handles it
  if (
    !options?.silent &&
    apiError.status !== 401 &&
    apiError.status !== 413 &&
    apiError.code !== 'FILE_TOO_LARGE' &&
    typeof window !== 'undefined'
  ) {
    const displayMessage = apiError.detail ?? apiError.message
    toast.error(displayMessage)
  }

  return apiError
}
