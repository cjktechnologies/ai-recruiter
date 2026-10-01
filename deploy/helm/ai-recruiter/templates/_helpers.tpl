{{- define "ar.name" -}}{{ .Release.Name }}{{- end -}}
{{- define "ar.labels" -}}
app.kubernetes.io/part-of: ai-recruiter
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}
{{- define "ar.apiImage" -}}{{ .Values.image.api.repository }}:{{ .Values.image.api.tag }}{{- end -}}
{{- define "ar.env" -}}
- name: ENVIRONMENT
  value: {{ .Values.environment | quote }}
- name: PUBLIC_BASE_URL
  value: {{ .Values.publicBaseUrl | quote }}
- name: CORS_ORIGINS
  value: {{ .Values.publicBaseUrl | quote }}
- name: OIDC_REDIRECT_URI
  value: "{{ .Values.publicBaseUrl }}/api/session/oidc"
{{- if .Values.redisTls.enabled }}
- name: REDIS_TLS_CA_CERT
  value: "{{ .Values.redisTls.mountPath }}/ca.pem"
{{- end }}
{{- range $k, $v := .Values.config }}
- name: {{ $k }}
  value: {{ $v | quote }}
{{- end }}
{{- end -}}
{{- define "ar.envFrom" -}}
- secretRef:
    name: {{ .Values.existingSecretName }}
{{- end -}}
{{- define "ar.podSecurity" -}}
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  runAsGroup: 10001
  fsGroup: 10001
  seccompProfile: { type: RuntimeDefault }
{{- end -}}
{{- define "ar.containerSecurity" -}}
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities: { drop: ["ALL"] }
{{- end -}}

{{- define "ar.redisTlsMount" -}}
{{- if .Values.redisTls.enabled }}
- { name: redis-tls, mountPath: {{ .Values.redisTls.mountPath }}, readOnly: true }
{{- end }}
{{- end -}}
{{- define "ar.redisTlsVolume" -}}
{{- if .Values.redisTls.enabled }}
- name: redis-tls
  secret:
    secretName: {{ .Values.existingSecretName }}
    items: [{ key: {{ .Values.redisTls.secretKey }}, path: ca.pem }]
{{- end }}
{{- end -}}
