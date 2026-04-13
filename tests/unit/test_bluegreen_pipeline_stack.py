import aws_cdk as core
import aws_cdk.assertions as assertions

from bluegreen_pipeline.bluegreen_pipeline_stack import BluegreenPipelineStack

# example tests. To run these tests, uncomment this file along with the example
# resource in bluegreen_pipeline/bluegreen_pipeline_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = BluegreenPipelineStack(app, "bluegreen-pipeline")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
