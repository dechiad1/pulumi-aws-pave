from pulumi.resource import ComponentResource, ResourceOptions
import pulumi_aws
from pulumi_aws import eks
from pulumi_aws import iam
from pulumi_aws import ec2
from pulumi_aws import autoscaling
from pulumi_kubernetes.core.v1 import ConfigMap
from pulumi_kubernetes import Provider
from pulumi import Output

import util.Util as Util


class Cluster(ComponentResource):
    """
    Create an EKS cluster with x nodes
    """

    def __init__(self, name, instance_type="t2.micro", node_count=0, vpc_id=None, key_name=None, subnet_ids=None,
                 version=None, bastion_sg_id=None, asg_tags=None):
        ComponentResource.__init__(self, "aws:compute:eks", name, None, None)
        self.vpc_id = vpc_id

        self._create_compute_iam_roles(name)
        self._create_sgs(bastion_sg_id)

        vpc_config = {
            "security_group_ids": [self.master_sg],
            "subnet_ids": subnet_ids
        }

        eks_tags = {
            "Name": name
        }
        cluster = eks.Cluster(name, name=name, role_arn=self.eks_master_role, tags=eks_tags, vpc_config=vpc_config,
                             __opts__=ResourceOptions(parent=self, depends_on=self.cluster_role_attachment_dependencies))

        eks_ami = _get_eks_ami(version)

        user_data = self._build_asg_userdata(cluster, name)
        node_launch_config = ec2.LaunchConfiguration("%s-launch-config" % name, image_id=eks_ami, instance_type=instance_type,
                                                     iam_instance_profile=self.eks_worker_instance_profile, key_name=key_name,
                                                     name=name, security_groups=[self.worker_sg],
                                                     user_data=user_data,
                                                     __opts__=ResourceOptions(parent=self))
        asg_tags = {
            "key": "kubernetes.io/cluster/%s" % name,
            "value": "owned",
            "propagateAtLaunch": True
        }
        node_asg = autoscaling.Group("%s-asg" % name, launch_configuration=node_launch_config.id, max_size=node_count,
                                     min_size=node_count, desired_capacity=node_count, vpc_zone_identifiers=subnet_ids,
                                     tags=[asg_tags], __opts__=ResourceOptions(parent=self, depends_on=[cluster]))

        # # TODO: create configmap to join the nodes to cluster
        # configmap_data = {
        #     "mapRoles" : [{
        #         "rolearn":self.eks_worker_role.arn,
        #         "username":"system:node:{{EC2PrivateDNSName}}",
        #         "groups":[
        #             "system:bootstrappers",
        #             "system:nodes"
        #         ]
        #     }]
        # }
        # configmap_metadata = {
        #     "name": "aws-auth",
        #     "namespace": "kube-system"
        # }
        #
        # k8s_provider = Provider("dtd-cluster", kubeconfig=cluster.certificate_authority)
        # join_nodes = ConfigMap("join-nodes-cm", data=configmap_data, metadata=configmap_metadata,
        #                        __opts__=ResourceOptions(parent=self, provider=k8s_provider))

        self.cluster_ca = cluster.certificate_authority['data']

    def _build_asg_userdata(self, cluster, name):
        user_data = Output.all(cluster.endpoint, cluster.certificate_authority).apply(lambda args: """
#!/bin/bash
set -o xtrace
/etc/eks/bootstrap.sh --apiserver-endpoint %s --b64-cluster-ca %s %s
""" % (args[0], args[1]['data'], name))

        print(user_data)
        return user_data

    def _build_kube_config(self, ca):
        pass

    def _create_compute_iam_roles(self, name):
        # According to AWS docs, this trust policy is required for the masters & the agents
        # TODO: can we curl for this & check if its different? use the updated one & log if different.
        # Note: multi line string requires open bracket here. Adding a newline results in a malformed policy doc
        mrp ="""{
"Version": "2012-10-17",
"Statement": [
    {
        "Effect": "Allow",
        "Principal": {
            "Service": "eks.amazonaws.com"
        },
        "Action": "sts:AssumeRole"
    }
]
}"""
        #Trust policy for the worker role
        wrp ="""{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ec2.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}"""

        policy_arn_string = "arn:aws:iam::aws:policy/"

        eks_master_role = iam.Role("eks-service-role", name="%s-master-role" % name, description="role for eks service", assume_role_policy=mrp,
                                   __opts__=ResourceOptions(parent=self))
        eks_worker_role = iam.Role("eks-service-worker-role", name="%s-worker-role" % name, description="role for eks worker nodes", assume_role_policy=wrp,
                                   __opts__=ResourceOptions(parent=self))
        eks_worker_instance_profile = iam.InstanceProfile("eks_worker_instance_profile", name="%s-instance-profile" % name,
                                                          role=eks_worker_role.id, __opts__=ResourceOptions(parent=self))

        # attach required policies to the master plane
        d1 = iam.PolicyAttachment("policy-AmazonEKSClusterPolicy", policy_arn="%sAmazonEKSClusterPolicy" % policy_arn_string, roles=[eks_master_role.id],
                             __opts__=ResourceOptions(parent=self))
        d2 = iam.PolicyAttachment("policy-AmazonEKSServicePolicy", policy_arn="%sAmazonEKSServicePolicy" % policy_arn_string, roles=[eks_master_role.id],
                             __opts__=ResourceOptions(parent=self))

        # attach required policies to the worker nodes
        iam.PolicyAttachment("policy-AmazonEKSWorkerNodePolicy", policy_arn="%sAmazonEKSWorkerNodePolicy" % policy_arn_string, roles=[eks_worker_role.id],
                             __opts__=ResourceOptions(parent=self))
        iam.PolicyAttachment("policy-AmazonEKS_CNI_Policy", policy_arn="%sAmazonEKS_CNI_Policy" % policy_arn_string, roles=[eks_worker_role.id],
                             __opts__=ResourceOptions(parent=self))
        iam.PolicyAttachment("policy-AmazonEC2ContainerRegistryReadOnly", policy_arn="%sAmazonEC2ContainerRegistryReadOnly" % policy_arn_string, roles=[eks_worker_role.id],
                             __opts__=ResourceOptions(parent=self))

        self.eks_master_role = eks_master_role.arn
        self.eks_worker_role = eks_worker_role
        self.cluster_role_attachment_dependencies = [d1, d2]
        self.eks_worker_instance_profile = eks_worker_instance_profile.name

    def _create_sgs(self, bastion_id=None):
        #TODO: if infra left up for a while, security groups cant be deleted. are they modified when running? Need a tag?

        # Create the security groups first
        master_sg = ec2.SecurityGroup("master-sg", vpc_id=self.vpc_id, description="security group for communication with the eks master plance",
                                      __opts__=ResourceOptions(parent=self))
        worker_sg = ec2.SecurityGroup("worker-sg", vpc_id=self.vpc_id, description="security group for communication with the worker nodes",
                                      __opts__=ResourceOptions(parent=self))

        # Create the egress/ingress rules for the master
        master_sg_egress = ec2.SecurityGroupRule("master-sg-egress", type="egress", cidr_blocks=["0.0.0.0/0"], from_port=0,
                                                 to_port=0, protocol=-1, security_group_id=master_sg.id,
                                                 __opts__=ResourceOptions(parent=self))
        current_ip = Util.get_workstation_ip()
        master_sg_ingress_workstation = ec2.SecurityGroupRule("master-sg-ingress-from-workstation", type="ingress", from_port=443, to_port=443,
                                                              protocol=-1, security_group_id=master_sg.id, cidr_blocks=["%s/32" % current_ip],
                                                              __opts__=ResourceOptions(parent=self))
        master_sg_ingress_nodes = ec2.SecurityGroupRule("master-sg-ingress-from-workers", type="ingress", from_port=0, to_port=0,
                                                        protocol=-1, security_group_id=master_sg.id, source_security_group_id=worker_sg.id,
                                                        __opts__=ResourceOptions(parent=self))

        # Create the egress/ingress rules for the workers
        worker_sg_egress = ec2.SecurityGroupRule("worker-sg-egress", type="egress", cidr_blocks=["0.0.0.0/0"], from_port=0,
                                             to_port=0, protocol=-1, security_group_id=worker_sg.id,
                                             __opts__=ResourceOptions(parent=self))
        worker_sg_ingress_itself = ec2.SecurityGroupRule("worker-sg-ingress-itself", type="ingress", from_port=0, to_port=0,
                                                         protocol=-1, security_group_id=worker_sg.id, self=True,
                                                         __opts__=ResourceOptions(parent=self))
        worker_sg_ingress_master = ec2.SecurityGroupRule("worker-sg-ingress-master", type="ingress", from_port=0, to_port=0,
                                                         protocol=-1, security_group_id=worker_sg.id, source_security_group_id=master_sg.id,
                                                         __opts__=ResourceOptions(parent=self))
        worker_sg_ingress_bastion = ec2.SecurityGroupRule("worker-sg-ingress-bastion", type="ingress", from_port=0, to_port=0,
                                                          protocol=-1, security_group_id=worker_sg.id, source_security_group_id=bastion_id,
                                                          __opts__=ResourceOptions(parent=self))

        self.master_sg = master_sg.id
        self.worker_sg = worker_sg.id

def _get_eks_ami(version):
    # remove the Patch from the version - its not used in AMI ids
    major_minor = ".".join(version.split('.')[:2])
    eks_node_version = "amazon-eks-node-%s-v*" % major_minor
    ami = pulumi_aws.get_ami(most_recent=True, owners=["amazon"], filters=[{"name": "name", "values" :[eks_node_version]}])
    return ami.id
