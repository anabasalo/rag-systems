# Pod Autoscaling in Kubernetes

This document is a small, self-contained sample used by the Phase 1
ingestion demo. It is intentionally a few hundred words long so the
chunker produces more than one chunk under the default settings.

## Horizontal Pod Autoscaler (HPA)

The Horizontal Pod Autoscaler automatically updates a workload resource,
such as a Deployment or StatefulSet, with the aim of automatically
scaling the workload to match demand. Horizontal scaling means deploying
more pods in response to increased load. This is different from
*vertical* scaling, which for Kubernetes would mean assigning more
resources, such as memory or CPU, to the pods that are already running
for the workload.

The HPA controller, running within the Kubernetes control plane,
periodically adjusts the desired scale of its target (for example, a
Deployment) to match observed metrics such as average CPU utilization,
average memory utilization, or any other custom metric you specify. The
controller fetches the metrics from either the resource metrics API
(for per-pod resource metrics) or the custom metrics API (for all other
metrics).

If the load decreases and the number of pods is above the configured
minimum, the HorizontalPodAutoscaler instructs the workload resource
(the Deployment, StatefulSet, or other similar resource) to scale back
down. Horizontal pod autoscaling does not apply to objects that cannot
be scaled, such as a DaemonSet.

## Vertical Pod Autoscaler (VPA)

The Vertical Pod Autoscaler is a separate component that adjusts the
CPU and memory requests and limits of containers based on observed
usage. Unlike the HPA, the VPA changes resource requests rather than
the number of replicas. The two are sometimes used together, but care
is required because adjusting requests can trigger pod restarts.

## Cluster Autoscaler

While the HPA and VPA scale workloads, the Cluster Autoscaler scales
the underlying nodes. When pending pods cannot be scheduled because of
resource pressure, the cluster autoscaler can add nodes; when nodes are
under-utilized for a sustained period, it can remove them. Cluster
scaling, pod scaling, and capacity planning together form the basis of
elastic, demand-driven Kubernetes operations.

## Notes

These three controllers are independent. They can be enabled together
but each is configured separately. In production, most teams adopt the
HPA first because it has the simplest mental model: more load implies
more pods, until a hard limit. The VPA and the Cluster Autoscaler are
typically introduced later, once observability around resource usage is
in place.
