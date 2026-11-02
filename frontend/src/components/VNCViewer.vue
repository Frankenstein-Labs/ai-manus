<template>
  <div
    ref="vncContainer"
    class="vnc-container"
    style="display: flex; width: 100%; height: 100%; overflow: auto; background: rgb(40, 40, 40);"
  ></div>
</template>

<script setup lang="ts">
import { ref, onBeforeUnmount, watch } from 'vue';
import { getVNCUrl } from '@/api/agent';
// @ts-expect-error - @novnc/novnc ships no type declarations
import RFB from '@novnc/novnc/lib/rfb';

const props = defineProps<{
  sessionId: string;
  enabled?: boolean;
  viewOnly?: boolean;
}>();

const emit = defineEmits<{
  connected: [];
  disconnected: [reason?: any];
  credentialsRequired: [];
}>();

const vncContainer = ref<HTMLDivElement | null>(null);
let rfb: RFB | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectDelay = 1000;
let disposed = false;

const clearReconnect = () => {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
};

const disconnect = () => {
  clearReconnect();
  const previous = rfb;
  rfb = null;
  previous?.disconnect();
};

const initVNCConnection = async () => {
  if (!vncContainer.value || !props.enabled || disposed) return;
  clearReconnect();
  const previous = rfb;
  rfb = null;
  previous?.disconnect();

  try {
    const connection = new RFB(vncContainer.value, getVNCUrl(props.sessionId), {
      credentials: { password: '' },
      shared: true,
      repeaterID: '',
      wsProtocols: ['binary'],
      scaleViewport: true,
    });
    rfb = connection;
    connection.viewOnly = props.viewOnly ?? false;
    connection.scaleViewport = true;

    connection.addEventListener('connect', () => {
      if (rfb !== connection) return;
      reconnectDelay = 1000;
      emit('connected');
    });

    connection.addEventListener('disconnect', (event: any) => {
      if (rfb !== connection) return;
      emit('disconnected', event);
      if (!disposed && props.enabled) {
        const delay = reconnectDelay;
        reconnectDelay = Math.min(reconnectDelay * 2, 30000);
        reconnectTimer = setTimeout(() => {
          reconnectTimer = null;
          void initVNCConnection();
        }, delay);
      }
    });

    connection.addEventListener('credentialsrequired', () => {
      if (rfb === connection) emit('credentialsRequired');
    });
  } catch (error) {
    console.error('Failed to initialize VNC connection:', error);
    if (!disposed && props.enabled) {
      const delay = reconnectDelay;
      reconnectDelay = Math.min(reconnectDelay * 2, 30000);
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        void initVNCConnection();
      }, delay);
    }
  }
};

watch([() => props.sessionId, () => props.enabled], () => {
  reconnectDelay = 1000;
  if (props.enabled && vncContainer.value) {
    void initVNCConnection();
  } else {
    disconnect();
  }
}, { immediate: true });

watch(vncContainer, () => {
  if (vncContainer.value && props.enabled) void initVNCConnection();
});

onBeforeUnmount(() => {
  disposed = true;
  disconnect();
});

defineExpose({
  disconnect,
  initConnection: initVNCConnection,
});
</script>
